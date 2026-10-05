# Olist: results and draft recommendation

Week 6, dataset 3 of 3. Every number below was produced by the app's own code from the joined file. Nothing was calculated by the AI. AI was off for this run, and the files stayed on the local computer.

Scenario figures are estimates that rest on the assumptions in section 3. They are not forecasts.

## 1. The data

- Source: the Brazilian E-Commerce Public Dataset by Olist, hosted on Kaggle under a CC BY-NC-SA 4.0 license. It holds about 100,000 orders placed on Brazilian online marketplaces. The license allows non-commercial use with credit. The data files are not stored in this repository.
- Three of the nine files were used: customers, orders and payments. The orders file holds the purchase date and status. The customers file holds a customer id that changes with every order, plus a unique customer id that identifies the real person. The payments file holds the money.
- How they were joined: each order was matched to its customer through the order's customer id, and the unique customer id was used as the customer. Payment rows were added up per order, because some orders were paid in several parts. The order value is the sum of the payments, so it includes shipping and any financing charges. Of 99,441 orders, one had no payment row and every order matched a customer.
- The file does not state a currency. I treat the amounts as Brazilian reais, based on the dataset's description, and have not confirmed this.
- Columns used by the app: the unique customer id, the purchase timestamp, the order value, the order id and the order status.
- Dates run from 2016-09-04 to 2018-09-03. The first months are very thin, with one order in September 2016, 300 in October 2016 and one in December 2016. The last month has a single order. Monthly figures at both ends should not be read closely.

## 2. What the app measured

Cleaning
- 1 order had no readable value and was removed. 625 orders had a canceled status and were removed. Nothing else was removed.
- 98,815 orders from 95,559 customers remain.
- Orders with other unfinished statuses were kept. These are 609 unavailable, 1,107 shipped, 314 invoiced, 301 processing, 5 created and 2 approved. They may overstate completed sales slightly.
- Total order value is 15,865,616.52 and the average order is 160.56.

Retention
- Only 3.1 percent of customers ordered again. 2,924 of 95,559 placed two or more orders. 92,635 customers placed exactly one order.
- 2.3 percent ordered again within 90 days, among the 78,112 customers whose first order was at least 90 days before the end of the file.
- The median time to a second order, among the customers who did return, is about 28 days.
- A new customer brings about 169.83 in revenue by month 12.
- Repeat customers placed 1.11 extra orders on average.

Segments
| Segment | Customers | Share of customers | Average orders | Average spend | Share of revenue |
|---|---|---|---|---|---|
| Champions | 1,074 | 1.1 percent | 2.2 | 323.48 | 2.2 percent |
| Loyal | 38,724 | 40.5 percent | 1.0 | 162.26 | 39.6 percent |
| New | 17,464 | 18.3 percent | 1.0 | 164.11 | 18.1 percent |
| At risk | 38,297 | 40.1 percent | 1.0 | 166.30 | 40.1 percent |
| Occasional | 0 | 0 percent | 0.0 | 0.00 | 0 percent |
| Lapsed | 0 | 0 percent | 0.0 | 0.00 | 0 percent |

Read this table with care. Almost every customer bought once, so the app's scores for how often a customer bought are ranked among near-identical customers. The result is that groups named Loyal and At risk, each with about one order per customer, are not loyal or at risk in any real sense. The segment names are not reliable on a dataset like this one. This is a limit of the app's method that this dataset exposed.

## 3. Assumptions for the scenario

These are placeholders chosen by the builder. The data has no ad spend, so none of them is a measurement. The ratios are the same as in the CDNOW and UCI runs, so the three can be compared.

- Horizon: 12 months.
- Marketing budget: 955,000. This is 12 percent of the file's revenue scaled to one year, rounded to the nearest thousand.
- Share spent on winning new customers today: 80 percent.
- Cost to win one customer: 176.61, which is 1.1 times the average order.
- Cost to bring one customer back: 44.96, which is 0.28 times the average order.
- Diminishing returns exponent: 0.8, the app's default.
- Extra orders per brought-back customer: 1.11, the observed average among the 3.1 percent of customers who returned on their own. This is the weakest input here. It assumes a customer who is won back will behave like one of the few who return unprompted.

## 4. Scenario results

| Cost to bring a customer back | Best shift | Estimated gain at the best shift | Gain at a 50 percent shift |
|---|---|---|---|
| 22.48, half the base | 50 percent | 2,219,870 | 2,219,870 |
| 44.96, the base case | 50 percent | 910,206 | 910,206 |
| 88.31, about double the base | 50 percent | 267,311 | 267,311 |
| 176.61, equal to the cost to win | 4 percent | 826 | negative 66,055 |

In the base case the best move is the 50 percent limit of what the tool tests, so the best size may be larger. The move beat today's split in all 2,000 simulated runs. When the two costs are equal, the best move is only about 4 percent, and it beat today's split in 98 percent of runs.

Moving money toward retention starts to pay above about 0.27 extra orders per brought-back customer at the base costs.

## 5. Draft recommendation

The tool favors moving budget toward retention under the base costs, but the evidence for it in this dataset is much weaker than in the other two. Only 3.1 percent of customers ever ordered again. The scenario favors retention because a brought-back customer is assumed to cost a quarter as much as a new one and to place about one extra order. Neither number comes from the data. If bringing a customer back costs about as much as winning a new one, the best move is close to zero.

A careful reading is: do not move a large share of the budget on this evidence. Test a small win-back campaign first, measure what share of contacted customers actually order again and what that costs, and set the split from that result.

The one thing the orders do show is that nearly every customer is a one-time buyer. For a marketplace like this, finding out why customers do not come back is likely worth more than shifting budget.

## 6. Limits to state honestly

- A marketplace dataset from 2016 to 2018. Customers here may buy from many different sellers, so repeat buying with Olist is a different thing from repeat buying with one store.
- No ad spend in the data. Both costs, the exponent and the budget are assumptions.
- The extra orders assumption comes from the 3.1 percent of customers who returned on their own. It probably overstates what spending would achieve.
- The segment names are not meaningful when almost every customer bought once.
- Some unfinished orders were kept, and the order value includes shipping and financing charges.
- The first and last months of the data are thin, so monthly figures at the edges are unreliable.
- No reviewer has rated this recommendation yet.

## 7. Check

These figures were produced by running the app's own cleaning, metrics and scenario code on the joined file. They have not been compared with the live app's screens. To check, upload the joined file from the local week6-data folder on the live app, map the columns as listed in section 1, and compare.
