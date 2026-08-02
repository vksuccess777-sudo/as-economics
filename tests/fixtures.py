"""A representative slice of real 9708 syllabus text, used to test the parser.

This is an excerpt chosen specifically because it contains every layout case
that broke a naive parser: page furniture between topics, "continued" repeat
headers for both units and topics, outcomes with bullet lists, wrapped outcome
lines, wrapped *bullet* lines, nested sub-bullets, the AS/A Level boundary, and
the command word table.

Kept short and quotation-limited on purpose — the full spine is generated on
the user's own machine from their own copy of the PDF, never committed.
"""

SYLLABUS_EXCERPT = """
3 Subject content
This syllabus gives you the flexibility to design a course that will interest, challenge and engage your learners.
Cambridge International AS Level candidates study topics 1.1-6.5.
AS Level content
1 Basic economic ideas and resource allocation (AS Level)
Candidates will explore the fundamental problem that underpins economics and a model highlighting some
of the main issues that arise from this problem.
1.1 Scarcity, choice and opportunity cost
1.1.1 fundamental economic problem of scarcity
1.1.2 need to make choices at all levels (individuals, firms, governments)
1.1.3 nature and definition of opportunity cost, arising from choices
1.1.4 basic questions of resource allocation
• what to produce
• how to produce
• for whom to produce
1.2 Economic methodology
1.2.1 economics as a social science
1.2.2 positive and normative statements (the distinction between facts and value judgements)
Cambridge International AS & A Level Economics 9708 syllabus for 2026, 2027 and 2028. Subject content
Back to contents page www.cambridgeinternational.org/alevel 16
1 Basic economic ideas and resource allocation (AS Level) continued
1.3 Factors of production
1.3.1 nature and definition of factors of production: land, labour, capital and enterprise
1.6 Classification of goods and services
1.6.3 nature and definition of merit goods: under-consumption as a result of imperfect information in the
market
2 The price system and the microeconomy (AS Level)
Candidates will examine how markets and the price mechanism determine the allocation of resources.
2.1 Demand and supply curves
2.1.1 effective demand
Cambridge International AS & A Level Economics 9708 syllabus for 2026, 2027 and 2028. Subject content
Back to contents page www.cambridgeinternational.org/alevel 18
2 The price system and the microeconomy (AS Level) continued
2.1 Demand and supply curves continued
2.1.2 individual and market demand and supply
4 The Macroeconomy (AS Level)
Candidates will consider national income as the most important measurement of macroeconomic
performance.
4.3 Aggregate Demand and Aggregate Supply analysis
4.3.8 shape of the AS curve in the short run (SRAS, upward sloping line or sweeping curve) and the long
run (LRAS, either a vertical line or in three sections - highly elastic, upward sloping, vertical)
6 International economic issues (AS Level)
Candidates will explore the theory of international trade between countries.
6.3 Current account of the balance of payments
6.3.1 components of the current account of the balance of payments:
• current account: trade in goods, trade in services, primary income and secondary income
• definition of balance and imbalances (deficit and surplus) in the current account of the balance of
payments
6.3.2 calculation of:
• balance of trade in goods
• current account balance (CAB)
A Level content
7 The price system and the microeconomy (A Level)
7.1 Utility
7.1.1 definition and calculation of total utility and marginal utility
9 The macroeconomy (A Level)
9.1 The circular flow of income
9.1.1 the multiplier process:
• calculation of:
- average and marginal propensities to save (aps and mps)
4 Details of the assessment
Calculators
Calculators may be used for all papers.
Command words
Command words and their meanings help candidates know what is expected from them in the exams.
Command word What it means
Analyse examine in detail to show meaning, identify elements and the relationship between
them
Assess make an informed judgement
Calculate work out from given facts, figures or information
Evaluate judge or calculate the quality, importance, amount, or value of something
5 What else you need to know
This section is an overview of other information you need to know about this syllabus.
"""
