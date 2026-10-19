# Browser PDF Editor

Free, browser-based PDF editor using Pyodide, PyMuPDF and supporting libraries. The application runs client-side, with no application server required for editing.

This repository contains only the independently deployable PDF Editor, not the main autonomo.help website.

## Run locally

```bash
python -m http.server 8080
```

Open http://localhost:8080. On a site, deploy these files in the static `/pdfeditor/` directory.

## Features

- Edit text and text frames
- Move PDF images and vector graphics
- Multi-page PDF editing and download

## Dependencies

Pyodide 0.29.4 from jsDelivr, PyMuPDF 1.28.2 wheel from PyPI, and pypdf/fontTools installed via micropip. Network connectivity is required for a first load. Check `index.html` for actual URLs.

## Licensing

This editor is intended to be released under GNU AGPL v3 or later, **subject to identifying and confirming all contributors' rights**. See LICENSING-BEFORE-PUBLISH.md and THIRD_PARTY_NOTICES.md. Do not treat this staging repository as license-complete until `LICENSE` has been populated with the unmodified full AGPL text and dependency notice obligations have been verified.

## Privacy

PDF processing is performed in the browser. No application endpoint for uploading PDF documents is required by this package; review hosting analytics, CDN requests, and production integrations before publishing a public privacy claim.
