#set page(paper: "a4", margin: (x: 1.8cm, y: 1.6cm))
#set text(size: 10pt)
#set par(justify: true)

#let accent = rgb("#2f5d8a")
#show heading.where(level: 2): it => block(above: 14pt, below: 7pt)[
  #text(size: 11pt, weight: "bold", fill: accent, upper(it.body))
  #v(-7pt)
  #line(length: 100%, stroke: 0.6pt + accent)
]

// One job, course or project: what, where, when, then its points.
#let entry(what, where, when, body) = block(below: 9pt)[
  #grid(columns: (1fr, auto), [*#what* · #where], text(fill: luma(90))[#when])
  #v(-3pt)
  #body
]

#align(center)[
  #text(size: 24pt, weight: "bold")[Your Name]
  #v(-6pt)
  Your City, Country · you\@example.com · 000 000 0000
]

== Profile
Two sentences: what you do well, and the kind of work you are after.

== Experience
#entry("Job title", "Company", "2024 – now")[
  - What you did, with a number in it.
  - Something you built or improved.
]
#entry("Earlier job", "Another company", "2022 – 2024")[
  - The thing you are proudest of there.
]

== Education
#entry("Degree or course", "Where", "2019 – 2022")[]

== Skills
Python · FastAPI · Linux · writing clearly
