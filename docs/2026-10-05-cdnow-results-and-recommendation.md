# CDNOW: results and draft recommendation

Week 6, dataset 1 of 3. Every number below was produced by the app's own code from the file. Nothing was calculated by the AI. AI was off for this run, and the file stayed on the local computer.

Scenario figures are estimates that rest on the assumptions listed in section 3. They are not forecasts.

## 1. The data

- Source: the CDNOW transaction history, a public dataset listed on Kaggle under a CC0 public domain license. It follows 23,570 customers who made a first purchase at CDNOW in early 1997, through the end of June 1998. This is an old data set from one cohort, so it describes that group and not a typical store today.
- Columns used: customer id, date, price. Price is the total dollar value of each purchase. The raw file confirms this, because price rises with quantity on the same rows. The quantity column was not used.
- File as loaded: 69,659 rows.

## 2. What the app measured

Cleaning
- 80 rows were removed because their order value was zero. Nothing else was removed.
- 69,579 orders from 23,502 customers remain, from 1997-01-01 to 1998-06-30.
- Total order value is 2,497,315.63 dollars, and the average order is 35.89 dollars.
- 255 rows exactly repeat another row and have no order id. They were kept, because identical orders can be real. With no order id in this file, each row counts as one order, so same-day purchases may be counted as separate orders and the repeat figures may run high.

Retention
- 49.6 percent of customers ordered again. 11,659 of 23,502 placed two or more orders.
- 30.1 percent ordered again within 90 days of their first order.
- The median time to a second order is 54 days.
- A new customer brings 89.18 dollars in revenue by month 12.
- Repeat customers placed 3.95 extra orders on average.

Segments
| Segment | Customers | Share of customers | Average spend | Share of revenue |
|---|---|---|---|---|
| Champions | 7,050 | 30 percent | 254.53 | 72 percent |
| Loyal | 3,732 | 16 percent | 74.04 | 11 percent |
| Occasional | 3,323 | 14 percent | 29.52 | 4 percent |
| At risk | 877 | 4 percent | 77.02 | 3 percent |
| Lapsed | 8,520 | 36 percent | 30.62 | 10 percent |
| New | 0 | 0 percent | 0.00 | 0 percent |

The New segment is empty because every customer in this file started in early 1997, well before the end of the data.

## 3. Assumptions for the scenario

These were chosen by the builder as placeholders. CDNOW has no ad spend, so none of them is a measurement.

- Horizon: 12 months.
- Marketing budget: 200,000 dollars. This is about 12 percent of the file's revenue scaled to one year.
- Share spent on winning new customers today: 80 percent.
- Cost to win one customer: 40 dollars.
- Cost to bring one customer back: 10 dollars.
- Diminishing returns exponent: 0.8, the app's default.
- Extra orders per brought-back customer: 3.95, the observed average for customers who returned on their own. This is the weakest input, because customers who need to be won back may order less.

## 4. Scenario results

| Costs to win and to bring back | Estimated gain from moving 50 percent of the budget to retention |
|---|---|
| 40 and 10, the base case | 784,388 |
| 40 and 5 | 1,762,728 |
| 40 and 20 | 295,217 |
| 40 and 40 | 50,632 |
| 20 and 10 | 590,434 |
| 20 and 20 | 101,264 |

In the base case the best move is 50 percent of the budget, which is the largest shift the tool tests, so the best size may be larger. The move beat today's split in all 2,000 simulated runs. These runs vary each uncertain input by about 25 percent. They do not test the structure of the model.

How sensitive it is to the extra orders assumption. With a cost to win of 40 and a cost to bring back of 10, moving money toward retention starts to pay above about 0.63 extra orders per brought-back customer. The threshold rises to about 1.25 at a cost to bring back of 20, and to about 2.5 when both costs are 40. At 0.5 extra orders, the best move reverses to about 12 percent of the budget toward new customers, with a gain of 4,904.

## 5. Draft recommendation

Under these assumptions, CDNOW should move a large part of its acquisition budget toward keeping existing customers, up to the 50 percent the tool tests. The case rests on three observed facts: about half of customers ordered again, customers who ordered again placed about four more orders, and the top 30 percent of customers brought 72 percent of revenue.

The size of the move depends on one number that orders cannot show: how many extra orders a customer who is won back with spend would place. If a won-back customer places more than about 0.6 extra orders and costs a quarter as much as a new customer, shifting budget pays. If won-back customers behave closer to half an extra order, the tool favors a small move the other way.

Recommended next step: test a win-back campaign aimed at the 877 at-risk customers and the 8,520 lapsed customers, measure how many extra orders they place, and set the budget split from that result.

## 6. Limits to state honestly

- Old data from a single cohort, and from a music store, so it is a demonstration of method and not a claim about stores today.
- No ad spend in the data. Both costs, the exponent and the budget are assumptions.
- Repeat figures may run high, because rows on the same day are counted as separate orders.
- The extra orders assumption comes from customers who returned on their own, so it likely overstates the effect of spending to win customers back.
- The best shift sits at the tool's 50 percent limit under most assumptions.
- No reviewer has rated this recommendation yet.

## 7. Check

The order counts, customer counts, repeat shares, days to a second order and segment sizes match what the live app showed on screen for the same file. The cleaned total of 2,497,315.63 also matches. The other money figures, such as the average order, the segment spend and the scenario results, were produced by running the app's own code on the file and have not yet been compared with the live screens after the quantity fix. The scenario table was produced by the same code the app runs.
