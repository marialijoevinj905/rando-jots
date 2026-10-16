import json, os
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
U = "2026-10-16T12:00:00Z"
S = {
 "cnbc_cpi":"https://www.cnbc.com/2026/10/14/stock-market-today-live-updates.html",
 "yahoo_cpi":"https://finance.yahoo.com/markets/live/stock-market-today-hot-inflation-report-drops-tech-drives-sp-500-nasdaq-down-152206632.html",
 "schwab_ppi":"https://www.schwab.com/learn/story/stock-market-update-open",
 "babypips":"https://www.babypips.com/news/financial-forex-market-recap-2026-10-15",
 "cnbc_1011":"https://www.cnbc.com/2026/10/11/stock-market-today-live-updates.html",
 "cnbc_tsmc":"https://www.cnbc.com/2026/10/15/tsmc-third-quarter-profit-global-ai-.html",
 "cnbc_banks":"https://www.cnbc.com/2026/10/13/bank-earnings-live-updates.html",
 "inv_banks":"https://www.investing.com/analysis/bank-earnings-q3-2026-goldman-30-beat-jpmorgan-misses-revenue-200689491",
 "qz_aapl":"https://qz.com/apple-stock-closes-above-5-trillion-first-time-nvidia-101526",
 "invlive":"https://investinglive.com/stocks/dow-leads-us-stock-rebound-indices-snatch-victory-from-the-jaws-of-defeat/",
 "coindesk":"https://www.coindesk.com/daybook-us/2026/10/15/bitcoin-copper-stocks-yields-all-fall-gold-rises",
 "tv_india":"https://www.tradingview.com/news/moodys:6a1a94efcbd37:0-stock-market-outlook-today-15-oct-sensex-nifty-prediction-djia-s-p-nasdaq-gift-nifty-kospi-nikkei-taiwan-cues/",
 "nvda":"https://www.heygotrade.com/en/news/nvidia-nvda-stock-news-october-15-2026/",
 "tape":"https://www.marketalleys.com/post/marketalleys-closing-tape-2026-10-15",
 "forbes_fed":"https://www.forbes.com/sites/digital-assets/2026/10/14/fed-66-likely-to-hold-rates-steady-following-high-inflation-data/",
 "cnbc_min":"https://www.cnbc.com/2026/10/07/fed-officials-see-another-hike-coming-but-no-sign-as-to-when-minutes-show.html",
 "schwab_sec":"https://www.schwab.com/learn/story/stock-sector-outlook",
 "brecorder":"https://www.brecorder.com/news/40444464/european-shares-hit-more-than-two-week-high",
 "ortex":"https://ortex.news/articles/188766/big-week-ahead-tesla-netflix-gm-report",
 "admiral_fed":"https://admiralmarkets.com/analytics/traders-blog/fed-rate-decision-october-2026",
}
snapshot = {"updatedAt":U,"asOfLabel":"Thu Oct 15, 2026 close",
 "tape":[
  {"label":"S&P 500","value":"7,744.06","chg":0.33},
  {"label":"Nasdaq","value":"26,713.03","chg":0.08},
  {"label":"Dow","value":"52,177.69","chg":1.08},
  {"label":"STOXX 600","value":"640.16","chg":0.38},
  {"label":"FTSE 100","value":"10,840","chg":1.1},
  {"label":"Nikkei 225","value":"64,426","chg":None,"note":"Fell as much as 3.5% intraday"},
  {"label":"Hang Seng","value":"24,063","chg":None,"note":"Closed lower on a tech selloff"},
  {"label":"Sensex","value":"72,781.89","chg":-0.34},
  {"label":"US 10Y","value":"5.08% · −11bp","chg":None},
  {"label":"Crude oil","value":"~$98","chg":2.2},
  {"label":"Gold","value":"~$4,170","chg":1.6},
  {"label":"Bitcoin","value":"~$82,300","chg":0.8},
  {"label":"Dollar index","value":"~102.0","chg":-0.5}],
 "regime":{"label":"Cautious: inflation and rate-hike risk","score":64,
  "summary":"Hot September CPI and a 1.3% jump in producer prices revived Fed hike fears, pushing the 10-year yield above 5%. Money is rotating out of AI and long-duration tech into value, energy, banks and defensives, while oil near $98 on Middle East tension adds to inflation pressure. Breadth is improving, so this reads as rotation more than a broad selloff."},
 "macro":[
  {"label":"Fed funds","value":"3.75–4.00%","note":"Hiked 25bp Sep 17; most officials see one more by year end"},
  {"label":"Next FOMC","value":"Oct 27–28","note":"Hold ~66–76% likely; Dec hike odds ~63%"},
  {"label":"Core PCE (Aug)","value":"3.0%","note":"Headline 3.4%; Fed sees 2% only by 2029"},
  {"label":"Sept CPI","value":"Above forecast","note":"Both headline and core beat estimates"},
  {"label":"PPI (m/m)","value":"+1.3%","note":"vs +0.5% expected; biggest core gain in 4 years"},
  {"label":"Breadth","value":">50% of S&P","note":"above 200-day average, up from ~40% in late Sep"}]}
quotes = {"updatedAt":U,"q":{
 "NVDA":{"name":"Nvidia","price":217.23,"chg":-1.84,"sector":"Semiconductors"},
 "TSM":{"name":"Taiwan Semiconductor","price":430.00,"chg":-3.4,"sector":"Semiconductors"},
 "MSFT":{"name":"Microsoft","price":539.44,"chg":1.08,"sector":"Software"},
 "AAPL":{"name":"Apple","price":342.00,"chg":-0.28,"sector":"Tech Hardware"},
 "GOOGL":{"name":"Alphabet","price":349.22,"chg":0.45,"sector":"Communication"},
 "META":{"name":"Meta Platforms","price":736.72,"chg":-0.11,"sector":"Communication"},
 "AMZN":{"name":"Amazon","price":254.76,"chg":0.27,"sector":"Consumer Discretionary"},
 "TSLA":{"name":"Tesla","price":362.44,"chg":-1.29,"sector":"Consumer Discretionary"}}}
N = lambda d,r,h,s,i,sec,t,src,u: {"date":d,"region":r,"headline":h,"summary":s,"impact":i,"sectors":sec,"tickers":t,"source":src,"url":S[u]}
news = {"updatedAt":U,"items":[
 N("Oct 15","United States","Producer prices jump 1.3% in September, more than double forecasts","The core PPI posted its biggest gain in four years. Stocks opened lower before recovering; yields fell late in the day. Adds to the case for further Fed tightening.","bearish",["Semiconductors","Software","Consumer Discretionary"],[],"Schwab","schwab_ppi"),
 N("Oct 14","United States","Hot September CPI revives Fed rate-hike fears; Nasdaq drops 1.9%","Headline and core inflation beat estimates. Rate-sensitive tech and financials fell hardest while energy led. Markets now price meaningful odds of a December hike.","bearish",["Semiconductors","Software","Tech Hardware","Communication"],["NVDA","MSFT"],"CNBC","cnbc_cpi"),
 N("Oct 15","Middle East","Oil climbs 2.2% to near $98 as Middle East tensions build","Reports say President Trump is weighing joining Saudi Arabia against Tehran-backed Houthis in Yemen. Higher crude supports energy producers but squeezes consumers and feeds inflation.","mixed",["Energy","Consumer Discretionary"],["XLE"],"BabyPips","babypips"),
 N("Oct 15","Asia","TSMC posts sixth straight record profit, guides Q4 to $52.3–54.3B","Revenue of $46.7B beat the top of guidance, but 66.4% gross margin slipped on the 2nm ramp. Shares closed down about 3.4% as investors focused on margin dilution and capex.","mixed",["Semiconductors"],["TSM","NVDA"],"CNBC","cnbc_tsmc"),
 N("Oct 15","United States","Nvidia falls as bond yields and debt-funded AI spending weigh","NVDA closed at $217.23, down 1.8%, extending the prior day's 3.2% drop. Investors are questioning AI infrastructure financing with the 10-year above 5%.","bearish",["Semiconductors"],["NVDA"],"Gotrade","nvda"),
 N("Oct 12","Asia","China's CXMT chip progress hits Micron, Samsung and SK Hynix","Memory makers sold off on fears of rising competition from China's CXMT, which reported progress on a new chip structure.","bearish",["Semiconductors"],["MU"],"CNBC","cnbc_1011"),
 N("Oct 13","United States","Goldman beats by ~30% on record equities trading; JPMorgan misses","GS earned $17.01 a share on $18.68B revenue. JPMorgan's $5.57 EPS missed $5.90 despite 13% NII growth. Bank of America took a $1.2B regulatory charge.","mixed",["Financials"],["GS","JPM","BAC"],"CNBC","cnbc_banks"),
 N("Oct 14","United States","Apple closes above $5 trillion market value for the first time","Apple has held up better than chip names during the AI selloff, acting as a relative safe haven within mega-cap tech.","bullish",["Tech Hardware"],["AAPL"],"Quartz","qz_aapl"),
 N("Oct 15","United States","Dow jumps 1.1% as money rotates from AI into value","More than half of S&P 500 stocks now trade above their 200-day averages, up from about 40% in late September. Leadership is broadening beyond mega-cap tech.","bullish",["Financials","Industrials","Healthcare"],[],"InvestingLive","invlive"),
 N("Oct 15","Global","Gold rises to ~$4,170 while bitcoin, copper and stocks slip","Gold gained 1.6% as investors sought hedges. Bitcoin swung below $81K with $485M in liquidations before ending near $82.3K.","mixed",["Commodities","Crypto"],["GLD"],"CoinDesk","coindesk"),
 N("Oct 15","Europe","European shares hit a two-week high; FTSE 100 up 1.1%","Banks lifted London while healthcare led the STOXX 600. A disputed Russia–Ukraine 'energy ceasefire' keeps European energy prices in focus.","bullish",["Financials","Healthcare","Energy"],[],"Business Recorder","brecorder"),
 N("Oct 15","India","Sensex slips 0.3% on wholesale inflation and high crude","India is a large oil importer, so $98 crude pressures its inflation and currency.","bearish",["Energy"],[],"TradingView","tv_india"),
 N("Oct 12","Global","Shipping stocks hit record highs on higher oil freight rates","Tanker and shipping names are benefiting from Middle East disruption and longer trade routes.","bullish",["Industrials"],[],"CNBC","cnbc_1011"),
]}
I = lambda sym,name,st,c,h,th,ri,tr,srcs: {"symbol":sym,"name":name,"stance":st,"conviction":c,"horizon":h,"thesis":th,"risks":ri,"trigger":tr,"sources":[{"name":n,"url":S[k]} for n,k in srcs]}
ideas = {"updatedAt":U,"items":[
 I("XLE","Energy sector ETF","Accumulate on dips",2,"3–6 months","Crude is near $98 on Middle East risk, energy led on the hot-CPI day, and Schwab rates Energy 'more favored'. Energy also hedges the inflation risk that hurts the rest of a tech-heavy portfolio.","A Mideast de-escalation or a real Russia–Ukraine energy deal could drop crude fast. Demand falls if the Fed over-tightens.","Crude falls back below ~$85, or a durable ceasefire takes the risk premium out.",[("BabyPips","babypips"),("Schwab sector view","schwab_sec")]),
 I("GS","Goldman Sachs","Buy candidate",2,"6–12 months","Q3 EPS of $17.01 beat consensus by about 30% on record equities trading. Higher-for-longer rates support bank income, and Financials are a favored sector.","Trading revenue is cyclical, and the beat is partly priced in after the jump. Credit stress rises if rates keep climbing.","Deal and trading activity slow, or credit spreads widen sharply.",[("CNBC","cnbc_banks"),("Investing.com","inv_banks")]),
 I("GLD","Gold","Hedge",2,"Ongoing","Gold is near $4,170 and rising while risk assets fall. Inflation is well above target and the Fed doesn't expect 2% until 2029. A 5–10% position can cushion an inflation or geopolitical shock.","Real yields above 5% on the 10-year compete with a non-yielding asset. Gold can pull back sharply after big runs.","Inflation clearly cools and the Fed signals cuts.",[("CoinDesk","coindesk"),("CNBC Fed minutes","cnbc_min")]),
 I("TSM","Taiwan Semiconductor","Watch: buy on weakness",2,"12+ months","Sixth straight record profit, revenue above guidance, and Q4 guided to $52.3–54.3B. The selloff is about margins, not demand, which can give long-term buyers a better entry.","2nm and overseas fab ramps dilute margins. Taiwan geopolitics. High multiples are sensitive to 5% yields and any AI capex slowdown.","Guidance is cut or big AI customers trim capex plans.",[("CNBC","cnbc_tsmc")]),
 I("NVDA","Nvidia and high-multiple semis","Trim if overweight",2,"Next 1–2 months","With the 10-year above 5% and hike odds rising, the highest-valuation AI names are being sold first. Memory chips also face new Chinese competition. Trimming an oversized position locks in gains and lowers rate risk.","AI earnings keep surprising; Nvidia reports in late November and could reverse the trend. Trimming has tax consequences.","Yields fall back below ~4.75%, or the hot inflation prints prove one-off.",[("Gotrade","nvda"),("CNBC","cnbc_cpi")]),
 I("T-bills","Short-term Treasuries","Park idle cash",3,"Until better entries","With policy at 3.75–4.00% and possibly higher, short T-bills pay close to the policy rate with almost no price risk while you wait for pullbacks.","Yields fall if the Fed pivots. You miss upside if stocks rally hard.","The Fed signals rate cuts.",[("Forbes","forbes_fed")]),
 I("XLV","Healthcare sector ETF","Buy candidate (defensive)",1,"6–12 months","Healthcare led European gains and is a favored sector. Its earnings depend less on rates and oil than tech or consumer names.","Drug-pricing policy risk. Lags in strong risk-on rallies.","Policy headlines target drug pricing directly.",[("Business Recorder","brecorder"),("Schwab sector view","schwab_sec")]),
 I("XLY","Consumer discretionary","Avoid for now",1,"Through Q3 earnings","Schwab's least-favored sector. $98 oil and higher borrowing costs squeeze spending, and Tesla reports Oct 21 after a 14.5% drop on its last report.","A cooling-inflation surprise would rally beaten-down names quickly.","Oil drops sharply or inflation cools.",[("Schwab sector view","schwab_sec"),("Ortex","ortex")]),
]}
cal = {"updatedAt":U,"items":[
 {"date":"2026-10-14","label":"September CPI","kind":"Macro","why":"Came in hot on headline and core; triggered the tech selloff."},
 {"date":"2026-10-15","label":"TSMC Q3 results","kind":"Earnings","why":"Beat, but margin guidance pressured chip stocks."},
 {"date":"2026-10-19","label":"MSCI index review ranking day","kind":"Index","why":"Ranks for the November rebalance; can move flows in affected names."},
 {"date":"2026-10-20","label":"Netflix after close; GE, GM, RTX, Northrop before open","kind":"Earnings","why":"First read on consumer and industrial demand under higher rates."},
 {"date":"2026-10-21","label":"Tesla Q3 after close","kind":"Earnings","why":"Consensus EPS ~$0.45; the stock fell 14.5% after its last report."},
 {"date":"2026-10-28","label":"FOMC rate decision (Oct 27–28)","kind":"Fed","why":"Hold expected; the statement and press conference set December hike odds."},
]}
for k,v in [("snapshot",snapshot),("quotes",quotes),("news",news),("ideas",ideas),("calendar",cal)]:
    json.dump(v, open(os.path.join(OUT, f"{k}.json"),"w"), indent=1)
print("ok")
