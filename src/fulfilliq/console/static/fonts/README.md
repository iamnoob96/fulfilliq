# Local editorial typefaces

These unmodified Google Fonts files are bundled so the console works without font-network requests:

- Fraunces — https://github.com/google/fonts/tree/main/ofl/fraunces
- DM Sans — https://github.com/google/fonts/tree/main/ofl/dmsans
- IBM Plex Mono — https://github.com/google/fonts/tree/main/ofl/ibmplexmono

Each family retains its SIL Open Font License in the adjacent `*-OFL.txt` file.
Streamlit serves the console script's `static/` directory at `/app/static/`. System serif,
sans-serif and monospaced fallbacks are declared in the console theme.
