# 1.1.0 verification

Blender 5.2.2 LTS, factory-startup isolated processes, 2026-10-09.

- Native Clean, Decimate Ratio/Error and Delete modify selected bone keys across two Actions.
- Unselected bones, similarly prefixed bone names, object channels, Action slots and curve modifiers remain intact.
- Locked curves and unsupported Constant interpolation are skipped.
- Escaped bone names match correctly; ambiguous multi-slot Actions are skipped.
- Injected native failure leaves source keys intact and removes temporary data.
- Operator registration and execution pass. All four editor contexts preserve editor type/mode.
- Ctrl toggle, Shift range, Ctrl+Shift additive range pass selection tests. All-page selection uses the same collection.
- Isolated foreground Delete Undo/Redo passes; popup screenshot inspected.
- Plain row button receives an actual simulated click. Modifier callbacks tested with explicit event objects because Blender synthetic UI clicks did not propagate modifier state to the button's invocation event; physical Ctrl/Shift input has not been automated.

The user's working blend file is never used as a test fixture.

1.1.0 additions:
- Bidirectional pose-bone checkbox selection and per-Action key counts pass.
- Action switch/current highlight, new/delete, independent duplicate and mirrored copy pass.
- Euler/Quaternion/Axis-Angle curve mirror signs, center bones, missing-pair preservation and double-flip identity pass.
- Actual fractional frame ranges update without changing keys; empty Actions skip.
- Generator progress and cancellation preserve sources and remove scratch data.
- Isolated foreground modal Clean across 25 Actions / 1000 curves passes native Undo/Redo, without manual after-operation undo push.
- Expanded bone/Action scroll lists and visible progress overlay screenshots inspected.
- Real synthetic Esc event cancels the modal operation, restores scratch data and preserves original keys.

# 1.2.0

- Blender 5.2.2 隔離 CLI：原本 headless、management 與新 rotation 測試通過。旋轉雙向換算比對全部取樣點的 Quaternion，另測試未選 Action 相容性阻擋、取消不寫回、注入提交失敗回復、時間軸向外取整及瀏覽清單選取切換。
- 循環測試：共同最早／最晚影格、短曲線補 Key、頭尾值與斜率相同、內部 Key 保留及鎖定曲線整體中止。
- 隔離 GUI：旋轉 modal 完成、Undo、Redo、Esc 取消通過；彈窗及進度截圖已檢視。原先大場景測試沒有產出完成標記，縮小隔離 fixture 後重測通過；不將未完成測試視為成功。
- 原生 Action 名稱欄位單擊事件確認切換 Action 並同步場景 1–20 範圍。雙擊改名使用 Blender UIList 原生名稱欄位；event_simulate 僅支援 PRESS／RELEASE／NOTHING，不能直接送 DOUBLE_CLICK，未宣稱實體雙擊已自動驗證。循環按鈕在複製前，實際點擊可開啟設定彈窗。
- 循環操作使用實際按鈕開啟並確認後，原生 Undo 還原頭尾控制柄通過；無手動補推操作後的 Undo 步驟。

# 1.2.1

- 新增 `test_cancel_gui.py`，使用獨立 `--factory-startup --enable-event-simulate` GUI，實際開啟／確認旋轉彈窗；12 Actions × 12 骨骼，總共 142704 筆取樣。在 75% 送 Esc 後下一次檢查（約 0.023 秒）已停止，曲線摘要與旋轉模式一致，浮層消失。
- 同樣 fixture 在 99% 寫回中點擊浮層取消按鈕，下一次檢查（約 0.023 秒）已停止，新增目標曲線回復，原曲線及模式一致。重測可設定 `CANCEL_PHASE=COMMIT`、`CANCEL_INPUT=CLICK`。
- 原版完整彈窗 fixture 在 90 秒尚未達取消門檻，故不將該次視為 Esc 重現成功。改版取消與寫回回復經實際輸入驗證。
- headless／management／rotation 測試全部通過，新增 Delete 與旋轉寫回中 generator.close 的回復檢查。GUI 旋轉正常完成、Undo、Redo、Esc 取消再次通過。

# 1.3.0

- Blender 5.2.2 隔離 CLI：headless／management／rotation／compose 全部通過；組合包含裁切與變速、選定骨骼覆蓋與空隙回復、Quaternion/Euler 轉換、取樣及寫入中取消、來源不變、預覽副本清理、骨骼全選／不選、完整 TRS 重設、空鎖定旋轉曲線忽略、成功後沒有 Key 的勾選骨骼模式同步，以及重新點選目前 Action 依最新 Key 更新範圍。
- `test_compose_gui.py`：獨立雙軌視窗、實際拖曳移動／裁切把手、複製區塊、設定彈窗確認、播放、Esc 關閉、處理進度與處理中 Esc 取消、產生新 Action、Undo／Redo 全部通過。原場景 Action／影格／範圍保持不變，關閉後清除預覽副本；高解析度尺寸與設定彈窗截圖已檢視。
- 合併批次彈窗的大量取樣取消回歸：142704 筆取樣於 75% 送 Esc，下一次檢查約 0.017 秒已停止，原曲線摘要與模式一致，未殘留浮層或暫存資料。
- 完全沒有動畫資料的來源空曲線不再造成旋轉誤阻擋。真正具有 Key 且鎖定／停用／修飾器／Sampled 的旋轉曲線仍需先整理；錯誤包含具體通道原因。
- 循環新增烘焙／解鎖副本：locked／mute／modifier／sampled 曲線處理、共同頭尾、來源不變及取消刪除副本通過；GUI 彈窗自動提供副本、顯示進度並可 Esc 取消。副本明確啟用原本停用的曲線，來源停用狀態保留。

# 1.3.1

- 自動旋轉測試涵蓋補選相容 Action、Cycles／鎖定／停用烘焙、空目標取代、取樣／寫回取消、Quaternion 等價取樣、其他通道保留、Action 名稱和目前使用者／NLA strip 重映射。
- 自動處理採原生 Action 副本：處理失敗或取消不更改原資料；Driver／不明確 Slot／多層等無法安全處理的情況預先取消。全部完成才替換原 Action，使用者連結與名称保留，資料 ID 改變。
- 隔離 GUI 實際輸入通過：提示窗取消、自動補選並烘焙 Cycles、進度中 Esc 取消、完成後原生 Undo／Redo。提示窗截圖已檢視。額外覆蓋 Sampled／缺少分量處理與 Driver 預先取消。

1.3.1 final scope: rotation controls are inline beneath Batch Keys, no selection or confirmation dialog. Automatic processing covers all source rotation Actions and all bones of the current armature; successful mode changes are global. `test_automatic_gui.py` verifies unselected bones/Actions, inline invocation, all Actions, Cycles baking, Esc rollback and native Undo/Redo. Earlier confirmation-window tests describe the superseded intermediate design.

`test_mirror.py`: compare evaluated bone pose matrices against armature-space reflection using asymmetric bone rolls, the user Hips basis, parent chains, root IK controls, mixed Euler/Quaternion, modifiers; double reflection recovers original matrices. Source is preserved and cancellation discards staging. `test_mirror_gui.py` verifies native dialog, modal progress, Esc, Undo/Redo. Read-only export of the user's 79-bone Turn_Right data passed an isolated FK reflection comparison (max matrix error < 1e-6); this fixture does not include the user's live constraints or mesh.
