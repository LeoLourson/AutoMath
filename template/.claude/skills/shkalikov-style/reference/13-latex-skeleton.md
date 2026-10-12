<!-- Мануал пользователя «shkalikov v3», разделы 19. Текст мануала не изменён. -->

# 19. LaTeX-шаблон и оформление документа

## 19.1. Важная оговорка

В текущем 28-файловом корпусе нет авторских `\newtheorem` и `\bibitem`:

- 0 вхождений `\newtheorem`;
- 0 вхождений `\bibitem`.

Это артефакт конвертации PDF → LaTeX / OCR, а не доказанный авторский выбор.

Поэтому ниже даётся **реконструкция**, основанная:

1. на печатной структуре статей;
2. на наблюдениях ручного мануала;
3. на жанровых конвенциях соответствующих журналов.

Пометка: `[реконструкция]`.

## 19.2. Минимальный каркас

```latex
\documentclass[12pt]{article}

\usepackage[T2A]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage[russian]{babel}
\usepackage{amsmath,amssymb,amsthm}

% Вариант 1: посекционная нумерация для крупных статей
\theoremstyle{plain}
\newtheorem{theorem}{Теорема}[section]
\newtheorem{lemma}[theorem]{Лемма}
\newtheorem{proposition}[theorem]{Предложение}
\newtheorem{corollary}[theorem]{Следствие}

\theoremstyle{definition}
\newtheorem{definition}[theorem]{Определение}

\theoremstyle{remark}
\newtheorem{remark}[theorem]{Замечание}

\numberwithin{equation}{section}

\renewcommand{\proofname}{Доказательство}
```

Для коротких статей можно использовать сквозную нумерацию:

```latex
\newtheorem{theorem}{Теорема}
\newtheorem{lemma}{Лемма}
\newtheorem{proposition}{Предложение}
```

## 19.3. Скелет статьи

```latex
\section{Введение}

Пусть $L$ — оператор, порождённый выражением
\begin{equation}
L(y)=\ldots
\end{equation}
в пространстве $L_2[0,1]$ на области
\begin{equation}
D(L)=\{y\in W_2^1[0,1] : \ldots\}.
\end{equation}

Цель работы — получить \ldots

\section{Основные определения}

\begin{definition}
Спектральную задачу \eqref{eq:1} назовём регулярной, если \ldots
\end{definition}

\section{Основные результаты}

\begin{theorem}
Пусть выполнены условия:
\begin{enumerate}
\item[(i)] \ldots;
\item[(ii)] \ldots.
\end{enumerate}
Тогда \ldots
Более того, \ldots
\end{theorem}

\section{Доказательство теоремы~1}

\begin{proof}
Доказательство разобьем на несколько шагов.

\smallskip\noindent\textbf{Шаг 1.} \ldots

\smallskip\noindent\textbf{Шаг 2.} \ldots

Теорема доказана.
\end{proof}

\begin{thebibliography}{99}
\bibitem{ref1} \ldots
\end{thebibliography}
```
