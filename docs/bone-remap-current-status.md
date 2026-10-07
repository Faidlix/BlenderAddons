# Faidlix Bone Remap 交接狀態

更新日期：2026-10-07。此檔記錄目前工作樹，不代表已發布到 GitHub 或安裝到正式 Blender。

## 問題與版本事實

- 正式 Blender 擴充目錄中的 `faidlix_bone_remap` 標示 0.6.7，且與 `repository/faidlix_bone_remap-0.6.7.zip` 的 `ui.py`、`operators.py`、`model.py` 內容一致。
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
- 尚未做前景窄側欄文字目視檢查，也尚未從 GitHub 正式 Repository 下載安裝測試。根目錄工作樹有許多既有未追蹤驗證檔，不可為了發布一併清除或提交。
- 正式 Blender 目前仍是 0.6.7；不可宣稱使用者正在用 0.6.8。

## 下一步

1. 在前景 Blender 以窄側欄檢查按鈕文字、動畫父列、時間欄與拖曳分隔線，必要時修正後重建 ZIP／索引 hash。
2. 用角色1003與 Run.fbx 目視比較來源和目標（含 IK／無 IK），特別複查手部控制器、Pole、Root 水平位移及播放中的前方軸即時更新；目前自動測試不足以宣稱這些已全部解決。
3. 發布前依 `CONTRIBUTING.md` 檢查受控改動、推送 GitHub，從 GitHub Repository 下載安裝正式測試。正式安裝前確認使用者已保存並關閉原 Blender；目前不得以本機 ZIP 隔離測試替代正式驗證。
