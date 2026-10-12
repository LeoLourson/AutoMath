module

public import Mathlib.Basic.Real.Basic
import Mathlib.Tactic.Ring

/-! # Пример модуля

Заголовок `module`, открытые импорты через `public import`, объявления в пространстве имён
проекта. Пример нужен, чтобы сборка и аудит аксиом работали с первого дня; замените его
первым настоящим утверждением. -/

public section

namespace __LIB__

/-- Квадрат суммы. На этой теореме `proj.py check` проверяет сборку и аксиомы. -/
theorem sq_add (a b : ℝ) : (a + b) ^ 2 = a ^ 2 + 2 * a * b + b ^ 2 := by
  ring

end __LIB__
