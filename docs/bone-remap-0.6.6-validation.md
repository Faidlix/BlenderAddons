# Faidlix Bone Remap 0.6.6 驗證紀錄

## 範圍

- 實作 UX 待辦 16～20：全部重設清理 IK、預覽／自動配骨冪等、清單共用欄寬、IK 線框顯示與腳部控制位置。
- 測試素材：`角色1003.blend`、`fairy-new-model.blend`、`Walk.fbx`、`Idle.fbx`、`Run.fbx`。
- `fairy-new-model.blend` 僅啟用 `Fairy_Idle` 與 `Fairy_Run`，其餘三個 FBX 各啟用一段動畫。

## 套件

- 版本：0.6.6。
- ZIP：`repository/faidlix_bone_remap-0.6.6.zip`。
- 大小：39215 bytes。
- SHA-256：`04bc7e864719eebcf3b91fc2e284b6426e1fb795625b4a880e20aaf8e5fc3b6f`。
- Repository 索引的版本、檔名、大小與雜湊均與 ZIP 相符。

## 自動測試結果

- 來源版 Headless 回歸：通過，輸出 `FBR_HEADLESS_OK`。
- 正式 ZIP 安裝於隔離的 Blender 5.2 使用者資源目錄後重新載入：版本 0.6.6，通過。
- 連續執行兩次自動配骨：來源 `matrix_world` 差異小於 `1e-6`；Target `matrix_world` 差異小於 `1e-6`。
- 全部重設：IK 控制骨、FBR IK 約束、`__FBR_IK_Shapes__`、`FBR_IK_SHAPE_*` 物件及無使用者 Mesh 均移除。
- IK 顯示：Shape 來源集合及物件維持隱藏、控制骨 `Wireframe` 開啟、`Scale to Bone Length` 關閉，大小下限為 `0.01`。
- README 下載連結與 Manager／Repository registry 靜態檢查：通過。

## 角色1003 五動作回歸

- 五個輸出 Action 均包含動態曲線，沒有被烘焙成靜止姿勢。
- 所有輸出的 Root Z 變化範圍為 0，未出現有 IK 後逐幀向下掉落。
- IK 控制點至腳骨端點的最大距離（角色高度 4.73467）：
  - `fairy-new-model_Fairy_Idle`：0.04490
  - `fairy-new-model_Fairy_Run`：0.19764
  - `Walk_Walk_N`：0.23570
  - `Idle_Idle`：0.43476
  - `Run_Run`：0.44751
- 全部結果低於角色高度的 12%，沒有先前漂浮在角色旁邊或遠離腳部的極端座標。

## MCP 與正式使用者安裝狀態

- 優先嘗試 Blender 5.2 MCP 背景驗證，但 MCP Server 未設定 `BLENDER_PATH`，回報找不到 `blender` 可執行檔。
- 因此依需求的後備方式，使用同一台電腦上的 Blender 5.2.2 LTS 命令列直接執行與隔離安裝驗證。
- 驗證期間偵測到既有 Blender 5.2 程序仍在執行，未覆寫其正式使用者擴充套件；需在該程序安全關閉後再安裝 0.6.6 並移除 0.6.5。
