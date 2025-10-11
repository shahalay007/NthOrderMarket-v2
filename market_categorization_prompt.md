# Market Categorization Prompt

You are given a prediction market title and optional metadata. Assign the market to exactly **one** category below. Return only the category number and label (e.g., `4 Cryptocurrency: Price (Immediate/Daily)`). If uncertain, choose the closest match; use `11 Miscellaneous` only when no other category reasonably applies.

1. **Sports: Soccer (Football)**  
   - Professional or international association football (soccer) matches, leagues, transfers, awards.  
   - Keywords: Premier League, FIFA, Champions League, club vs club, Euro qualifiers.

2. **Sports: North American Leagues (NHL, MLB, NFL, NBA)**  
   - Ice hockey (NHL), baseball (MLB), American football (NFL), basketball (NBA) plus related awards, drafts, and postseason outcomes in these leagues.  
   - Includes college matchups only when explicitly tied to these leagues’ drafts or awards.

3. **Sports: Combat & eSports (Gaming, Fighting, Cricket)**  
   - Combat sports (boxing, MMA, UFC), wrestling, motorsports, golf, tennis, cricket, and all esports or fantasy outcomes not covered in Categories 1–2.  
   - Includes college sports (NCAA), other regional leagues, and fantasy sports performance metrics.

4. **Cryptocurrency: Price (Immediate/Daily)**  
   - Intraday or single-day price direction ("up or down"), prices on specific calendar dates, hourly ranges, or near-term thresholds for any cryptocurrency.  
   - Includes markets referencing exact dates/times for Bitcoin, Ethereum, Solana, etc.

5. **Cryptocurrency: Products & Futures (Tokens, ETFs, Price Targets)**  
   - Token launches, ETFs, protocol upgrades, reserve announcements, long-term price targets, on-chain metrics, or corporate crypto holdings that extend beyond a single day.  
   - Includes NFTs, exchanges, and airdrops.

6. **Politics: U.S. Domestic & Legal**  
   - U.S. elections, legislation, legal outcomes, government appointments, scandals, and political figures’ actions within the United States.  
   - Covers state/local races, Supreme Court, federal agencies, partisan topics.

7. **Politics: Global & Military Conflict**  
   - International elections, geopolitical negotiations, sanctions, conflicts, military actions, treaties, or regime changes outside the U.S.  
   - Includes multinational relations involving the U.S. when the focus is foreign policy or conflict.

8. **Technology & Business (Product Releases, AI, IPOs)**  
   - Technology launches, software features, AI benchmarks, corporate strategy, mergers/acquisitions, IPO valuations, or venture topics not dominated by crypto.  
   - Includes automotive tech (EVs), aerospace, and consumer hardware.

9. **Media & Entertainment (Awards, Celebs, Content Views)**  
   - Film, TV, music releases, celebrity relationships, social media metrics, streaming numbers, awards (Oscars, Grammys), book/game launches when primarily entertainment.  
   - Includes influencer content performance.

10. **Finance & Economics (Earnings, Macro Indicators)**  
    - Corporate earnings, analyst beats/misses, stock indices, inflation, GDP, employment, interest rates, or traditional finance regulations.  
    - Includes commodities (gold, oil) and macroeconomic reports.

11. **Miscellaneous**  
    - Science, weather, natural disasters, religion, health crises, or any market not clearly fitting Categories 1–10.  
    - Use sparingly after confirming no other category applies.

When classifying:
- Focus on the market’s primary subject. If multiple subjects exist, choose the most dominant theme.  
- Treat fictional or hypothetical versions as belonging to the closest real-world category.  
- For compound markets, identify the central question (e.g., "NBA MVP" ➝ Category 2).  
- If a market is cryptocurrency-related but centers on macro policy, pick Categories 4 or 5 depending on scope.  
- If a market is economic but explicitly about legislation or a political figure, favor Category 6 or 7.  

Output format: ``<category number> <category label>``.
