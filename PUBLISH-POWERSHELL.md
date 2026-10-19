# Manual GitHub publication (PowerShell)

1. Create a new **Public**, empty repository on GitHub, e.g. `pdf-editor-browser`. Do not initialize README/license there.
2. Finish `LICENSING-BEFORE-PUBLISH.md`, especially add the full `LICENSE` file.
3. In the unpacked directory run:

```powershell
git init
git branch -M main
git add .
git status --short
git commit -m "Initial release: browser PDF editor"
git remote add origin https://github.com/YOUR_ACCOUNT/pdf-editor-browser.git
git push -u origin main
```

4. Open the repository URL and confirm files are public, especially source, LICENSE and notices.
5. Only then add public `Source code & licenses` link to your deployed editor and enable the public route.

Do not run these commands from C:\Projects\autonoma-easy-prep. This is a different repository.
