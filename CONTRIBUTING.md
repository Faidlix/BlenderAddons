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
11. 只有選配的 Faidlix Manager 可以註冊 3D Viewport 的「全部更新」面板；個別外掛不得包含 `_faidlix_update_all.py` 或其他全域更新面板副本。
12. Manager 至少偵測到兩個已安裝的 Faidlix 套件才顯示，完成文字保留 1 秒後必須恢復為「全部更新」。
13. 共通功能的程式、Panel、Operator、狀態與流程只實作在 `addons/Faidlix_Manager/`；其他外掛只保留自己的功能。
14. 其他外掛新增、改名或變更共通能力時，必須同步 `addons/Faidlix_Manager/addon_registry.json` 的套件 ID、顯示名稱、能力與排序；未登錄套件不得由 Manager 執行共通功能。
15. `addon_registry.json` 只存宣告式資訊，不可放 Python callback、類別或對其他外掛的 import；個別外掛仍不得依賴 Manager。
16. 每次新增或更新外掛 ZIP，根目錄 `README.md` 必須同步更新該外掛名稱、版本與直接 ZIP 連結；連結文字固定為「外掛名稱 版本」，點擊後直接下載 `repository/<套件 ID>-<版本>.zip`。
17. 發布前必須執行 `tests/test_readme_download_links.py`，確認 README 的每個下載連結與 `repository/index.json` 完全一致且檔案存在。
