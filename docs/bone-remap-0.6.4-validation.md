# Faidlix Bone Remap 0.6.4 專案驗證報告

- 驗證日期：2026-10-05
- 結果：**未通過**
- 停止條件：更新外掛後累計 20 次外掛操作仍無法得到與來源相近的動畫，依測試要求停止。
- 正式版本：`0.6.4`
- 發布 commit：`33904c0e6c1c2e6b1299f6601fb76b80dc6a4dbe`
- 正式套件 SHA256：`0CD0B73D9BC97BD888EDB581F23A990A2528103A0CD436ABDF41BEE28B250397`

## 測試範圍

- Target：`角色1003.blend` / `Armature`
- 來源：
  - `fairy-new-model.blend`：只啟用 `Fairy_Idle`、`Fairy_Run`
  - `Walk.fbx`：`Walk_N`
  - `Idle.fbx`：`Idle`
  - `Run.fbx`：`Run`
- Fairy 骨架自動對應 79 根骨頭；FBX 共用骨架自動對應 65 根骨頭。
- Fairy 與 FBX 兩組獨立映射各設定一次腳部 IK。

## 操作計數

正式套件更新完成後才開始計算：

1. 正式安裝套件最小重新定向測試：1 次。
2. 舊程序的匯入、配骨、IK 與重新定向測試：11 次。
3. 乾淨專案批次測試：單次批次匯入、2 次自動配骨、4 次 IK Start/OK、1 次重新定向，共 8 次。

合計：`20/20`。

## 通過項目

- 正式 GitHub 套件下載內容、大小與 SHA256 和發布產物一致。
- 安裝後載入版本確認為 `0.6.4`。
- 五個預期輸出 Action 均建立成功。
- Root Z 範圍：
  - `fairy-new-model_Fairy_Idle`：`0.0`
  - `fairy-new-model_Fairy_Run`：`2.3283064365386963e-10`
  - `Walk_Walk_N`：`4.656612873077393e-10`
  - `Idle_Idle`：`0.0`
  - `Run_Run`：`0.0`
- IK 控制骨 `FBR_IK_Left_Foot`、`FBR_IK_Right_Foot` 均為 `Deform = false`。
- 本次沒有再出現逐幀累積向下掉落或非有限數值。

## 失敗項目

- 輸出 Action 雖然有完整幀範圍與大量 F-Curve，但動畫數值被烘焙成第一幀的常數，角色實際不動。
- `Run_Run` 在第 1、5、10、15、20 幀的 Hips、左大腿、左小腿、左腳與左上臂最終姿勢完全相同。
- 例如 `Run_Run` 的 Hips 四條 quaternion 曲線從第 1 幀到第 20 幀的值域皆只有單一數值；左上臂亦相同。
- Hips 的 Y location 固定約 `200.0745544`，顯示根骨位移縮放或座標轉換仍有另一個明顯問題。
- 因輸出是靜止姿勢，無法判定為與來源 Idle、Run、Walk 相近。

## 高可能原因

匯入來源會由 `_move_to_temporary_collection()` 設為 `hide_set(True)`。預覽流程會暫時解除來源隱藏，但 `iter_bake_clip()` 在逐幀讀取 `source_pose.matrix_basis` 前沒有同樣解除來源隱藏或強制從 depsgraph 取得逐幀求值物件。GUI 模式下，隱藏來源在重新定向期間很可能只保留第一幀求值，導致每一幀都寫入相同姿勢。

另需獨立檢查 `auto_scale` 使用 `source_obj.dimensions.length` 與 `target_obj.dimensions.length` 的時機；目前輸出根骨 Y 位移約 200，表示尺寸或物件縮放可能被重複套用。

## 保留與還原

- 完整失敗案例：`C:\Users\faidl\Desktop\3DAI測試\角色1003_0.6.4失敗測試.blend`
- 測試前備份：`C:\Users\faidl\Desktop\3DAI測試\BlenderAddons\backups\角色1003.before-bone-remap-20261005-031410.blend`
- 正式 `角色1003.blend` 已由測試前備份還原，還原後 SHA256 與備份相同。

## 下一個修正方向

1. 在 `iter_bake_clip()` 進入時保存來源顯示狀態，暫時解除 View Layer 隱藏；完成或失敗時於 `finally` 還原。
2. 或改用 `context.evaluated_depsgraph_get()` 與 `source_obj.evaluated_get()` 讀取每幀來源姿勢，不依賴隱藏物件的即時更新。
3. 新增 GUI 模式回歸測試，明確驗證來源至少一根動態骨頭的輸出 F-Curve 值域大於零；不能只檢查 Action、曲線或幀數存在。
4. 以相同五段素材重測根骨位移縮放，確認不再出現約 200 單位的固定偏移。
