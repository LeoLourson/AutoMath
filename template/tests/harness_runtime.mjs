// Contract check against the real, pinned Harness packages. No LLM calls.
// node tests/harness_runtime.mjs /path/to/node_modules [--mcp]
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
if (!process.argv[2]) throw new Error('Pass the node_modules directory containing @deepseek-ai/dsh');
const modules = resolve(process.argv[2]);
const requireDsh = createRequire(resolve(modules, '@deepseek-ai/dsh/package.json'));
const load = name => import(pathToFileURL(requireDsh.resolve(name)).href);
const manifest = JSON.parse(await readFile(resolve(root, 'output/harness/generated.json'), 'utf8'));
const installed = JSON.parse(await readFile(resolve(modules, '@deepseek-ai/dsh/package.json'), 'utf8'));
assert.equal(installed.version, manifest.dsh_version, 'Validate with the pinned Harness version');
const [{ insert: entries }] = JSON.parse(await readFile(resolve(root, 'output/harness/cordis.patch.yml'), 'utf8'));
for (const entry of entries) {
  const plugin = await load(entry.name);
  const validated = await plugin.Config['~standard'].validate(entry.config);
  assert.equal(validated.issues, undefined, `${entry.id}: ${JSON.stringify(validated.issues)}`);
}
console.log(`Native plugin schemas: ${entries.length} passed`);

const { FileSystemSkillProvider } = await load('@deepseek-ai/dsh-skill-filesystem');
const controller = new AbortController();
const warnings = [];
const context = { get: () => undefined, logger: { warn: text => warnings.push(text) } };
const config = entries.find(entry => entry.id === 'research-skills').config;
const provider = new FileSystemSkillProvider(context, {
  signal: controller.signal, invalidate() {},
}, { ...config, watch: false });
try {
  const skills = await provider.list({ cwd: root, signal: controller.signal });
  assert(Array.isArray(skills), 'Discovery must complete without warnings');
  const expected = Object.keys(manifest.inventory.skills).length;
  assert.equal(skills.length, expected);
  assert.equal(warnings.length, 0, warnings.join('\n'));
  for (const skill of skills) {
    const loaded = await provider.get(skill, { cwd: root, signal: controller.signal });
    assert(loaded.content.length > 0);
    assert.equal(loaded.invocation.userInvocable, true);
    assert.equal(loaded.invocation.modelInvocable, manifest.inventory.skills[loaded.name].model_invocable);
  }
  console.log(`Native skill discovery and loading: ${skills.length} passed`);
} finally {
  await provider.dispose();
}

if (process.argv.includes('--mcp')) {
  const { Client } = await load('@modelcontextprotocol/client');
  const { StdioClientTransport } = await load('@modelcontextprotocol/client/stdio');
  for (const entry of entries.filter(entry => entry.name.endsWith('dsh-mcp-client'))) {
    const { serverName, command, args, cwd } = entry.config;
    const client = new Client({ name: 'research-template-check', version: '1.0.0' }, {
      capabilities: {}, versionNegotiation: { mode: 'auto' },
    });
    const transport = new StdioClientTransport({ command, args, cwd, stderr: 'inherit' });
    try {
      await client.connect(transport);
      const { tools } = await client.listTools();
      assert(tools.length > 0, `${serverName}: no tools`);
      const probe = { proj: 'overview', lit: 'papers' }[serverName];
      if (probe) {
        assert(tools.some(tool => tool.name === probe));
        const result = await client.callTool({ name: probe, arguments: {} });
        assert(!result.isError, `${serverName}: probe failed`);
        assert(!JSON.stringify(result).includes('ОШИБКА:'), `${serverName}: application error`);
      }
      console.log(`MCP ${serverName}: ${tools.length} tools; ${probe ?? 'discovery'} passed`);
    } finally {
      await client.close();
      await transport.close();
    }
  }
}
