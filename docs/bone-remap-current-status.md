# Faidlix Bone Remap 交接狀態

更新日期：2026-10-07。此檔區分 GitHub 發布、隔離安裝與正式 Blender 安裝；三者不可混為一談。

## 問題與版本事實

- 更新前正式 Blender 擴充目錄中的 `faidlix_bone_remap` 標示 0.6.7，且與 `repository/faidlix_bone_remap-0.6.7.zip` 的 `ui.py`、`operators.py`、`model.py` 內容一致。
- 工作樹原始碼也曾標示 0.6.7，但上述三檔內容不同；正式 0.6.7 沒有工作樹後續加入的「使用 Pole」、Pole 長度／大小比與浮動 IK 編輯視窗。發布前查詢 GitHub `main` 的來源及索引為 0.6.4（2026-10-07）；推送後必須重新讀回確認。
- 使用者的畫面中，來源前方／Target 前方按鈕文字空白，T-Pose／播放文字遭截斷，動畫父列仍未依要求顯示 `檔名(動畫數量)`。使用者要求先前 IK 功能也一併修正。

## 本次已改動

- 將原始碼版本改為 0.6.8，避免再用相同版本號表示不同內容。
- `ui.py`：多動畫父列改為 `檔名(數量 個動畫)`；多動畫選擇器與預覽操作各自獨立成行；來源／Target 前方改為明確文字的軸向按鈕。檔案移除為垃圾桶，啟用標題空白、單動畫仍為 `檔名 / 動畫名`（原始碼已具備，正式 0.6.7 未同步）。
- `operators.py`：新增 `fbr.set_forward_axis`，經原屬性更新流程重建預覽；`tests/test_headless.py` 補軸向按鈕行為測試。
- `model.py`、`operators.py`、`retarget.py`、`tests/test_headless.py`、`tests/test_project_retarget.py` 保留工作樹先前未發布的 Pole、IK 烘焙與預覽修正；本次未把它們誤當成正式 0.6.7 已安裝功能。
- `docs/ui-design-guidelines.md` 補「窄側欄不可讓操作文字消失」；`.cursor/rules/bone-remap-handoff.mdc` 規定接手時讀本文件、同步版本及區分測試層級。
- `__init__.py`、`blender_manifest.toml`、`ui.py`、根目錄 `README.md`、`repository/index.json` 與 `repository/faidlix_bone_remap-0.6.8.zip` 已改為一致的 0.6.8。

## 驗證／發布狀態

- 0.6.8 隔離 headless 單元測試：已通過 `FBR_HEADLESS_OK`，涵蓋預覽、自動配骨架、自動對軸向、IK 控制骨／Pole 的基本行為與新前方按鈕。
- 角色1003 專案重定向測試：`FBR_PROJECT_RETARGET` 已通過，五段動畫有動態曲線；腳 IK 控制器在測試取樣影格與目標腳的最大距離約 0.00957 Blender 單位。測試只覆蓋其設計的情境，不等於目視確認全部手腳動畫與來源一致。
- ZIP：Blender 建置、metadata validate、隔離 `user_default` 安裝、模組及新 operator 讀回通過；`ui.py` 位元組與原始碼一致。ZIP 44338 bytes，SHA-256 `f6a76bc09575bce9ddfd56455de36f397519f046bcaccb59c49bbb826c3e6478`，已寫入索引。
- 根目錄 `tests/test_readme_download_links.py` 通過 `README_DOWNLOAD_LINKS=PASS`。
- GitHub `main` 的 0.6.8 發布提交 `ccefcc61fa50568436efcd6c661752d702ff9ed2` 已以 `git ls-remote` 讀回；後續驗證紀錄另有提交。由 GitHub raw 下載的 0.6.8 ZIP 為 44338 bytes，SHA-256 與索引相同；在全新隔離 Blender 使用者目錄安裝、啟用後讀回 `(0, 6, 8)` 與新 operator 成功。
- 確認 Blender 沒有執行後，將原正式擴充備份至 `backups/faidlix_bone_remap-0.6.7-before-0.6.8-20261007`，再由 GitHub 下載 ZIP 重新安裝至 `FaidlixBlenderAdd_ons`。正式安裝目錄 manifest 是 0.6.8，七個套件檔案逐一與下載 ZIP 位元組相同；尚未驗證線上更新按鈕與前景操作。
- 尚未做前景窄側欄文字目視檢查。根目錄工作樹有許多既有未追蹤驗證檔，未納入發布，也不可為了發布一併清除或提交。
- 正式磁碟安裝為 0.6.8，但尚未在使用者前景 Blender 以此版本完成目視驗證；不要把磁碟安裝與執行中畫面視為同一件事。

## 下一步

1. 在前景 Blender 以窄側欄檢查按鈕文字、動畫父列、時間欄與拖曳分隔線，必要時修正後重建 ZIP／索引 hash。
2. 用角色1003與 Run.fbx 目視比較來源和目標（含 IK／無 IK），特別複查手部控制器、Pole、Root 水平位移及播放中的前方軸即時更新；目前自動測試不足以宣稱這些已全部解決。
3. GitHub 推送、遠端 ZIP 比對與正式磁碟安裝已完成；仍需打開 Blender，在前景核對外掛版本、線上更新狀態及實際操作。隔離／背景測試不得替代這一步。
