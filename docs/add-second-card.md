# Add a second card to CCGeek

## Scope

Add one card to the existing Outlook import and Streamlit dashboard. Keep the existing HSBC TravelOne import and milestone working. Show each card's transactions and spend independently. Add milestone progress for the new card if the owner supplies its target and qualifying rules. The second card is AU Zenith⁺ Visa ending in 3052 with INR billing.

- Outlook source is `Finance → Banks → AU` in the existing mailbox. Import all available purchase alerts.
- AU sends purchase alerts from `creditcard.alerts@aubank.in` with the subject `AU Bank Credit Card Transaction Alert`. Its template gives a masked card suffix, INR amount, merchant, and transaction date and time in day-month-year and 12-hour format.
- Annual milestones are ₹8,00,000 for the ₹5,000 fee waiver and ₹12,00,000 for Taj Epicure. Both periods run from November 12 through November 11.
- The monthly target is ₹75,000 for 1,000 reward points. The implementation treats the 23rd as the closing day, so the window runs from the 24th through the following 23rd.
- Progress uses imported INR purchases. Refunds, fees, issuer exclusions, and foreign-currency conversion require separate rules.

Once deployed, use **Add AU Zenith⁺** to enroll the card and **Sync emails** to import history. Use synthetic or redacted alert fixtures.

## Implementation map

1. Start with `app/cli.py`, `app/db/enums.py`, and `app/db/models/card.py`. Reuse the existing card record and enrollment command where supported. Check the current last-four lookup and CLI duplicate check. If the suffix overlaps an existing card, resolve identity using the issuer and any additional identifier available in the alert. Ambiguous alerts should appear in diagnostics without being assigned automatically.
2. In `app/graph/client.py` and `app/graph/constants.py`, reuse nested folder resolution and pagination. Use the supplied folder path and preserve the existing HSBC source. If the folder is shared by two cards, scan it once and route each message to its card. Preserve both HSBC templates in `app/parser/hsbc.py` and add parsing only if the new alerts require it. Use the normalized fields in `app/parser/models.py`.
3. Update the shared importer in `app/sync.py` so both the CLI and dashboard import to the correct active card. Keep message-ID deduplication and make folder, parsing, and unmatched-card failures visible. Apply any agreed backfill cutoff to the parsed transaction date.
4. In `app/ui/streamlit_app.py`, select the card by database ID. Scope milestone progress, monthly spend, top merchants, transaction history, and CSV export to that card. Preserve the current HSBC milestone settings. Use the selected card's currency for display and apply any agreed foreign-currency rules before calculating totals. If the new card has no milestone, still show its spending and transaction history.

## Acceptance checks

- Import representative alerts for both cards and confirm the stored card, decimal amount, currency, merchant, and transaction date for each.
- Run sync twice and verify that the second run adds no duplicates. Check that ambiguous card matches and malformed alerts are reported.
- Switch cards in the dashboard and verify that spend, charts, transaction history, and CSV export follow the selection. Confirm that the HSBC milestone remains based on HSBC TravelOne transactions.
- If the second card has a milestone, check both date boundaries, the remaining amount, and the agreed eligibility rules. Verify the requested backfill once the owner can run an authenticated sync.
