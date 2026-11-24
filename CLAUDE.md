# Arbetssätt för det här repot

Varje ändring i `espp_tracker/` ska ha:
1. En ny post överst i `espp_tracker/CHANGELOG.md` (Keep a Changelog, på svenska) – Home Assistant visar filen i appens Changelog-flik.
2. Höjt versionsnummer i `espp_tracker/config.yaml` (annars ser Home Assistant ingen uppdatering). Patch för fixar, minor för nya funktioner.
3. Samma version i changelogg-posten, så att de alltid stämmer överens.
