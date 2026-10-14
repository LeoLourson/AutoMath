"""Индекс полных текстов: смысловая и словарная близость, выдача куска.

Модель загружается лениво и держится в памяти: сервер `lit` прогревает её при запуске,
потому что под Windows загрузка из обработчика запроса зависает. Индекс — производное, он
пересобирается по изменившимся текстам и лежит вне Git.
"""
from __future__ import annotations

import bisect
import json
import re
import sqlite3
from pathlib import Path

from sources import papers, paths, registry, tex, web

MODEL = 'intfloat/multilingual-e5-small'
CHUNKER = 3  # увеличить после изменения нарезки: индекс пересоберётся
CHUNK = 1000  # знаков; в LaTeX это около 450 токенов при пределе модели 512
_model = None
_corpus = None


def embed(texts: list[str], prefix: str):
    """Нормированные векторы e5: ONNX Runtime на процессоре, усреднение по токенам."""
    global _model
    import numpy as np
    if _model is None:
        import onnxruntime
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        def cached(name: str) -> str:
            try:
                return hf_hub_download(MODEL, name, local_files_only=True)
            except OSError:
                return hf_hub_download(MODEL, name)

        tokenizer = Tokenizer.from_file(cached('tokenizer.json'))
        tokenizer.enable_truncation(max_length=512)
        tokenizer.enable_padding(pad_id=tokenizer.token_to_id('<pad>') or 0, pad_token='<pad>')
        _model = tokenizer, onnxruntime.InferenceSession(cached('onnx/model.onnx'),
                                                         providers=['CPUExecutionProvider'])
    tokenizer, session = _model
    inputs = {item.name for item in session.get_inputs()}
    vectors = np.zeros((len(texts), 1), dtype='float32')
    order = sorted(range(len(texts)), key=lambda i: len(texts[i]))  # близкие длины — меньше дополнения
    for start in range(0, len(order), 16):
        batch = order[start:start + 16]
        encoded = tokenizer.encode_batch([prefix + texts[i] for i in batch])
        mask = np.array([item.attention_mask for item in encoded], dtype='int64')
        feed = {'input_ids': np.array([item.ids for item in encoded], dtype='int64'), 'attention_mask': mask}
        if 'token_type_ids' in inputs:
            feed['token_type_ids'] = np.zeros_like(mask)
        hidden = session.run(None, feed)[0]
        pooled = (hidden * mask[..., None]).sum(1) / mask.sum(1, keepdims=True)
        if vectors.shape[1] != pooled.shape[1]:
            vectors = np.zeros((len(texts), pooled.shape[1]), dtype='float32')
        vectors[batch] = pooled / np.linalg.norm(pooled, axis=1, keepdims=True)
    return vectors.astype('float16')


def connect() -> sqlite3.Connection:
    paths.DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(paths.DB)
    db.execute('create table if not exists meta(key text primary key, value text)')
    version = f'{MODEL}:{CHUNKER}'
    if db.execute("select value from meta where key = 'version'").fetchone() != (version,):
        with db:  # другая модель или нарезка: старый индекс несовместим
            for table in ('chunks', 'fts', 'papers'):
                db.execute(f'drop table if exists {table}')
            db.execute("insert or replace into meta values ('version', ?)", (version,))
    db.executescript('''
        create table if not exists papers(code text primary key, stamp text);
        create table if not exists chunks(id integer primary key, code text, seq integer, kind text,
            label text, section text, file text, loc integer, page text, text text, vec blob);
        create index if not exists chunks_code on chunks(code, seq);
        create virtual table if not exists fts using fts5(text, section, tokenize='unicode61 remove_diacritics 2');
    ''')
    return db


def text_file(row: dict) -> Path | None:
    """Файл для индекса: LaTeX, а без него текстовый слой PDF."""
    if row.get('tex') and (paths.LIT / row['tex']).exists():
        return paths.LIT / row['tex']
    if row.get('filename') and (paths.LIT / row['filename']).with_suffix('.txt').exists():
        return (paths.LIT / row['filename']).with_suffix('.txt')
    return None


def index(codes: list[str] | None = None, log=None) -> list[str]:
    """Индексирует новые и изменившиеся тексты; остальные пропускает."""
    db, report = connect(), []
    stamps = dict(db.execute('select code, stamp from papers'))
    for row in registry.load():
        code, path = row['code'], text_file(row)
        if codes and code not in codes:
            continue
        if path is None:
            if codes:
                report.append(f'{code}: текста для индекса нет')
            continue
        raw = path.read_bytes()
        stamp = registry.sha256(raw)
        if stamps.get(code) == stamp:
            continue
        text = raw.decode('utf-8').replace('\r\n', '\n')
        chunks = tex.tex_chunks(text) if path.suffix == '.tex' else tex.txt_chunks(text)
        if log:
            log(f'{code}: {len(chunks)} кусков, считаю векторы')
        title = f"{row['title']}. {row.get('title_en', '')}"
        vectors = embed([f"{title}. {chunk['section']}. {chunk['text']}" for chunk in chunks], 'passage: ')
        with db:
            db.execute('delete from fts where rowid in (select id from chunks where code = ?)', (code,))
            db.execute('delete from chunks where code = ?', (code,))
            for seq, (chunk, vector) in enumerate(zip(chunks, vectors)):
                rowid = db.execute(
                    'insert into chunks(code, seq, kind, label, section, file, loc, page, text, vec) '
                    'values (?,?,?,?,?,?,?,?,?,?)',
                    (code, seq, chunk['kind'], chunk['label'], chunk['section'], path.name, chunk['loc'],
                     chunk['page'], chunk['text'], vector.tobytes())).lastrowid
                db.execute('insert into fts(rowid, text, section) values (?,?,?)',
                           (rowid, chunk['text'], chunk['section']))
            db.execute('insert or replace into papers values (?,?)', (code, stamp))
        report.append(f'{code}: {len(chunks)} кусков из {path.name}')
    db.close()
    return report


def corpus(db: sqlite3.Connection):
    """Матрица векторов индекса; перечитывается после изменения базы."""
    global _corpus
    import numpy as np
    stamp = paths.DB.stat().st_mtime_ns
    if _corpus is None or _corpus[0] != stamp:
        rows = db.execute('select id, code, kind, vec from chunks order by id').fetchall()
        matrix = np.frombuffer(b''.join(row[3] for row in rows), dtype='float16').reshape(len(rows), -1)
        _corpus = (stamp, [row[0] for row in rows], [row[1] for row in rows], [row[2] for row in rows],
                   matrix.astype('float32'))
    return _corpus[1:]


def place(file: str, loc: int, page: str) -> str:
    if file.endswith('.tex'):
        return f'output/literature/{file}:{loc}' + (f', печатная с. {page}' if page else '')
    return f'{Path(file).stem}.pdf, стр. файла {loc}'


def search(query: str, k: int = 8, codes: list[str] | None = None, kind: str | None = None,
           log=None) -> str:
    """Гибридный поиск: BM25 по словам и близость векторов, объединённые по рангам."""
    import numpy as np
    index(log=log)
    db = connect()
    ids, paper_codes, kinds, matrix = corpus(db)
    if not ids:
        return 'Индекс пуст: в output/literature/ нет текстов.'
    allowed = np.array([(not codes or code in codes) and (not kind or kind.lower() in item.lower())
                        for code, item in zip(paper_codes, kinds)])
    scores: dict[int, float] = {}
    similarity = np.where(allowed, matrix @ embed([query], 'query: ')[0].astype('float32'), -1.0)
    for rank, position in enumerate(np.argsort(-similarity)[:100]):
        if allowed[position]:
            scores[ids[position]] = 1 / (60 + rank)
    words = re.findall(r'\w{2,}', query.lower())
    if words:
        permitted = {chunk for chunk, ok in zip(ids, allowed) if ok}
        lexical = [rowid for (rowid,) in db.execute(
            'select rowid from fts where fts match ? order by bm25(fts) limit 2000',
            (' OR '.join(f'"{word}"' for word in words),)) if rowid in permitted][:100]
        for rank, rowid in enumerate(lexical):
            scores[rowid] = scores.get(rowid, 0) + 1 / (60 + rank)
    papers = {row['code']: row for row in registry.load()}
    out = []
    for rowid in sorted(scores, key=scores.get, reverse=True)[:k]:
        code, item, label, section, file, loc, page, text = db.execute(
            'select code, kind, label, section, file, loc, page, text from chunks where id = ?', (rowid,)).fetchone()
        paper = papers[code]
        head = [f"#{rowid} {code} {paper['authors'].split(';')[0].split()[-1]}, «{paper['title'][:70]}»",
                item + (f' {label}' if label else '')]
        if section:
            head.append('§ ' + section[:70])
        out.append(' · '.join(head + [place(file, loc, page)]) + '\n    ' + web.squash(text)[:340])
    db.close()
    return '\n'.join(out) or 'Ничего не найдено.'


def show(rowid: int, around: int = 0) -> str:
    """Полный текст куска и его соседей по статье."""
    db = connect()
    found = db.execute('select code, seq from chunks where id = ?', (rowid,)).fetchone()
    if not found:
        return f'Куска #{rowid} нет в индексе.'
    out = []
    for ident, item, label, section, file, loc, page, text in db.execute(
            'select id, kind, label, section, file, loc, page, text from chunks where code = ? and seq between ? '
            'and ? order by seq', (found[0], found[1] - around, found[1] + around)):
        out.append(f"#{ident} {found[0]} · {item}{' ' + label if label else ''} · § {section} · "
                   f"{place(file, loc, page)}\n{text}\n")
    db.close()
    return '\n'.join(out)
def listing() -> str:
    db = connect()
    counts = dict(db.execute('select code, count(*) from chunks group by code'))
    db.close()
    return '\n'.join(
        f"{row['code']} · {row['version']} · {row['authors'].split(';')[0]} · {row['title'][:80]} · "
        f"{counts.get(row['code'], 0)} кусков" for row in registry.load()) or 'Реестр пуст.'
