# Faidlix Bone Remap 0.6.7 驗證紀錄

## 版本與封裝

- 版本：0.6.7。
- ZIP：`repository/faidlix_bone_remap-0.6.7.zip`。
- 大小：41966 bytes。
- SHA-256：`87aac6c7fb7305f610a1e656ef0ca0fc6bfca9cc6d58ca1e9ec24a855137ef84`。
- 隔離 Blender 5.2 使用者資源安裝成功，匯入、註冊與解除註冊皆通過。

## 實作重點

- IK 改為端點控制骨、Pole 控制骨與下肢／前臂 solver 約束；預設 chain 2、iterations 500、顯示大小 0.05。
- 每幀烘焙完整端點矩陣與 Pole 位置，並以 Target Armature 物件空間處理，避免腳部控制器漂移。
- FBX 位移縮放使用「原始匯入比例 × 對位倍率」的完整有效比例，不再漏掉常見的 0.01 FBX 縮放。
- T-Pose／動畫預覽的來源骨架為實心黃色，並在自動配骨、自動對軸向後保持預覽類型、影格與對位尺寸。
- 來源／Target 前方軸改為按鈕，在預覽時可動態重建動畫。
- 軸向與 IK 編輯改為彈出視窗；軸向視窗含 Solo，關閉後恢復所有骨頭隱藏狀態。
- 動畫清單與骨骼對應清單改為直接拖曳欄位分隔線，標題與內容同步調整，不再顯示數值比例列。

## 驗證結果

- `tests/test_headless.py`：通過，輸出 `FBR_HEADLESS_OK`。
- `角色1003.blend` 專案測試：重新映射 `fairy-new-model.blend` 的 Fairy_Idle／Fairy_Run，以及 Walk／Idle／Run FBX，共 5 段輸出皆保持動態曲線。
- 專案測試已驗證 Pole 骨存在、非 Deform、IK chain=2、iterations=500。
- IK 控制器到腳部最大誤差約 0.00957，相對角色尺寸約 0.7%；Root Z 範圍為 0，未再出現批次重定向持續下墜。
- 連續兩次自動配骨後來源對位矩陣不變，Target 物件矩陣不變。

## 正式安裝

- 使用者關閉原本有未儲存變更的 Blender 後，已備份正式 0.6.6 到 `backups/faidlix_bone_remap-before-0.6.7-20261006`。
- Blender 擴充安裝命令回報 `STATUS Reinstalled "faidlix_bone_remap"`。
- 正式 manifest 版本為 0.6.7；直接從正式安裝目錄匯入、註冊與解除註冊成功。
- 正式安裝版已確認 `FBR_OT_drag_column` 與 `FBR_OT_axis_solo` 操作器存在。
- MCP 背景啟動器因未設定 `BLENDER_PATH` 無法啟動；依備援規則改用 Blender 本身背景模式完成相同驗證，未儲存或改動角色檔。
