#set document(title: "Report title")
#set page(paper: "a4", margin: (x: 2.4cm, y: 2.6cm), numbering: "1")
#set text(size: 11pt)
#set par(justify: true)
#set heading(numbering: "1.1")

#align(center)[
  #text(size: 22pt, weight: "bold")[Report title]
  #v(2pt)
  #text(size: 12pt)[Your name · #datetime.today().display("[day] [month repr:long] [year]")]
]
#v(8mm)
#outline()
#pagebreak()

= Introduction
What this report is about, and why it matters, in a paragraph.

= Findings
The main result first. @results shows the numbers.

#figure(
  table(
    columns: 3,
    align: (left, right, right),
    [*Measure*], [*Before*], [*After*],
    [Start-up, s], [4.1], [1.3],
    [Memory, MB], [820], [310],
  ),
  caption: [Before and after the change.],
) <results>

== Details
- The first thing worth knowing.
- The second.

= Conclusion
What to do next.
