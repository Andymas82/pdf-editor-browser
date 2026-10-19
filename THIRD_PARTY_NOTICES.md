# Third-party license inventory (review before release)

| Package | Version | Reported license | Upstream |
|---|---|---|---|
| PyMuPDF / MuPDF | 1.28.2 | AGPL-3.0 or commercial | https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright |
| Pyodide | 0.29.4 | MPL-2.0 (runtime bundles components with other licenses) | https://github.com/pyodide/pyodide |
| pypdf | installed by micropip (not pinned) | BSD-3-Clause | https://github.com/py-pdf/pypdf |
| fontTools | installed by micropip (not pinned) | MIT | https://github.com/fonttools/fonttools |

Do not assume this is an exhaustive list: review transitive dependencies and bundled notices in the exact distributed runtime. Preserve attribution/license texts as required. Pin pypdf/fontTools versions before final compliance sign-off.
