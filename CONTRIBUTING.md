# Faidlix 外掛搬移與發布規範

1. 所有正式外掛都放在 `main` 的 `addons/<AddonName>/`，不以 Git 分支當作外掛分類。
2. 每個外掛必須是自給自足的 Blender Extension，具有獨立 `blender_manifest.toml`、套件 ID、版本、README 與測試。
3. 外掛不得 `import` 其他 Faidlix 外掛，也不得把 Faidlix Manager 當作必要相依。
4. 每個外掛必須能單獨建置 ZIP、單獨安裝、單獨更新、單獨停用與移除。
5. 所有套件 ZIP 放在根目錄 `repository/`，由同一個 `index.json` 列出；每個套件 ID 在索引中只保留最新版 ZIP。
6. 個別外掛的線上更新及 Manager 都使用 `https://raw.githubusercontent.com/Faidlix/BlenderAddons/main/repository/index.json`。
7. Manager 只能更新已安裝的套件；不得把未安裝外掛當成相依自動安裝。
8. 搬移現有外掛時必須保留原套件 ID，並提升版本，讓 Blender 視為原外掛的更新。
9. 舊 Repository 至少發布一個遷移版，讓現有使用者可以切換至新的共用來源，不得直接中斷舊安裝的更新路徑。
10. 每次發布都必須先執行 Blender 背景測試、驗證 ZIP 與索引，推送 GitHub 後，再從 GitHub Repository 下載安裝正式測試。
