# UCI Online Retail: results and draft recommendation

Week 6, dataset 2 of 3. Every number below was produced by the app's own code from the file. Nothing was calculated by the AI. AI was off for this run, and the file stayed on the local computer.

Scenario figures are estimates that rest on the assumptions in section 3. They are not forecasts.

## 1. The data

- Source: the UCI Machine Learning Repository, Online Retail dataset, licensed CC BY 4.0. It holds the orders of a UK online retailer that sells all-occasion gifts, many of them to wholesale customers. Prices are in pounds sterling.
- The file as downloaded has 541,909 rows. The dates in the file run from 2010-12-01 to 2011-12-09.
- This is a sample. The app accepts at most 200,000 rows, so I kept a random sample of customers with all of their orders. I used a fixed random seed of 42 and rows from 2,095 of the 4,372 customers that have an id. This gave 189,985 rows.
- Rows with no customer id were left out of the sample. There were 135,080 of them, and the app drops them anyway, because it cannot link them to a customer.
- Columns used: CustomerID, InvoiceDate, UnitPrice, InvoiceNo and Quantity.
- UnitPrice is the price of one item, so the order value was read as price times quantity. This was checked on the first rows of the file. A row with a price of 3.75 and a quantity of 24 is a line worth 90.00, and reading 3.75 as the whole line would be wrong. Across the usable rows the average line value is 3.09 if price is read as a total and 24.40 if it is read as a price of one item.
- Rows that share an invoice number were combined into one order, by adding their line values.

Because it is a sample of customers, the totals below describe the sample and not the whole retailer. Rates such as the repeat share should be close to the full file's rates, but I did not check that against the full file.

## 2. What the app measured

Cleaning
- 4,405 rows had a negative value, which are the returns and cancellations, and they were removed. 20 rows had a value of zero and were removed.
- 176,459 rows were extra lines of an order and were added into their orders.
- 9,101 orders from 2,077 customers remain. 18 sampled customers dropped out because all of their rows were returns or zero value.
- Total order value is 4,528,405.57 pounds and the average order is 497.57 pounds.

Retention
- 66.4 percent of customers ordered again. 1,380 of 2,077 placed two or more orders.
- 48.0 percent ordered again within 90 days, among the 1,602 customers whose first order was at least 90 days before the end of the file.
- The median time to a second order is about 50 days.
- A new customer brings about 4,784.81 pounds in revenue by month 12.
- Repeat customers placed 5.09 extra orders on average.

Segments
| Segment | Customers | Share of customers | Average orders | Average spend | Share of revenue |
|---|---|---|---|---|---|
| Champions | 468 | 22.5 percent | 11.4 | 6,484.78 | 67.0 percent |
| Loyal | 356 | 17.1 percent | 3.9 | 1,698.34 | 13.4 percent |
| New | 475 | 22.9 percent | 1.7 | 630.74 | 6.6 percent |
| At risk | 378 | 18.2 percent | 3.1 | 1,199.15 | 10.0 percent |
| Lapsed | 400 | 19.3 percent | 1.0 | 340.11 | 3.0 percent |
| Occasional | 0 | 0 percent | 0.0 | 0.00 | 0 percent |

## 3. Assumptions for the scenario

These are placeholders chosen by the builder. The data has no ad spend, so none of them is a measurement.

- Horizon: 12 months.
- Marketing budget: 532,000 pounds. This is 12 percent of the sample's revenue scaled to one year, rounded to the nearest thousand. The same ratio was used for CDNOW.
- Share spent on winning new customers today: 80 percent.
- Cost to win one customer: 547.33 pounds, which is 1.1 times the average order.
- Cost to bring one customer back: 139.32 pounds, which is 0.28 times the average order.
- These two ratios match the CDNOW run, so the two datasets can be compared.
- Diminishing returns exponent: 0.8, the app's default.
- Extra orders per brought-back customer: 5.09, the observed average for customers who returned on their own. This is the weakest input.

## 4. Scenario results

Estimated gain from moving 50 percent of the budget to retention, unless a different best move is shown.

| Cost to bring a customer back | Best shift | Estimated gain at the best shift | Gain at a 50 percent shift |
|---|---|---|---|
| 69.66, half the base | 50 percent | 4,647,082 | 4,647,082 |
| 139.32, the base case | 50 percent | 1,312,036 | 1,312,036 |
| 273.66, about double the base | 5 percent | 5,220 | negative 325,142 |
| 547.33, equal to the cost to win | negative 19 percent, toward new customers | 244,034 | negative 1,174,092 |

In the base case the best move is the 50 percent limit of what the tool tests, so the best size may be larger. The move beat today's split in all 2,000 simulated runs. At double the base retention cost, it beat today's split in 98 percent of runs, with a best move of about 5 percent.

How sensitive it is to the extra orders assumption. At the base costs, moving money toward retention starts to pay above about 2.46 extra orders per brought-back customer. The observed average is 5.09, so the result holds only if won-back customers behave at least about half as well as customers who returned on their own.

## 5. Draft recommendation

Under these assumptions, this retailer should move budget toward keeping existing customers, but the size of the move depends heavily on what a win-back costs. When bringing a customer back costs about a quarter of what winning a new one costs, the tool favors moving as much as it tests. When retention costs about half as much as acquisition, the best move shrinks to about 5 percent. When the two cost the same, the best move reverses toward new customers.

The case for retention rests on observed facts in the sample. Two thirds of customers ordered again, repeat customers placed about five more orders on average, and 468 Champions brought 67 percent of revenue.

Recommended next step: before moving budget, find out what it actually costs to win back a lapsed or at-risk customer and how many orders those customers place afterward. Run a small win-back test on the 378 at-risk and 400 lapsed customers in the sample and set the split from the result.

## 6. Limits to state honestly

- A sample of customers, not the full file, from one UK gift wholesaler and retailer. Repeat rates here are high, partly because many customers are businesses that reorder, so they should not be generalized to a typical consumer store.
- The 4,405 removed rows are returns and cancellations. They were dropped, not netted against earlier orders, so customer values may be slightly overstated.
- No ad spend in the data. Both costs, the budget and the exponent are assumptions.
- The extra orders assumption comes from customers who returned on their own, so it likely overstates the effect of spending to win customers back.
- The best shift sits at the tool's 50 percent limit under the base case.
- Dates run to 2011-12-09 in the file. The dataset's listing page, as I read it, gave a shorter period that ends in September 2011. I did not resolve the difference, so I report the dates as found in the file.
- No reviewer has rated this recommendation yet.

## 7. Check

These figures were produced by running the app's own cleaning, metrics and scenario code on the sampled file. They have not been compared with the live app's screens. To check, upload the sample file in the live app, answer the order value question with the price of one item, and compare.
