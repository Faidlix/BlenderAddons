# Faidlix_BatchCleanKey 1.0.0

Blender 5.2+ 獨立 Extension。Pose Mode 選取骨骼後，在 3D View、Dope Sheet、Action Editor 或 Graph Editor 的 N 側邊欄 → Faidlix → Faidlix_BatchCleanKey → 批次處理 Action Keys。

彈出窗：單擊 Action 單選；Ctrl+單擊增選／減選；Shift+單擊選取錨點至目前列的範圍；Ctrl+Shift 加入範圍。提供全選與取消全選。Action 清單按名稱排序，顯示所選骨骼的 Key 數量，預選目前 Action。

清單每頁 10 個 Action，使用上一頁／下一頁切換；跨頁保留選取和 Shift 錨點，全選涵蓋所有頁。

- Delete：移除所選骨骼全部 Key，保留空通道與 Action、其他骨骼及物件通道。
- Clean：使用 Blender 原生 Clean，設定閾值。它會依 Blender 規則調整控制柄，請檢查動畫結果。
- Decimate：使用 Blender 原生縮減，支援移除比例（0.5 = 移除約一半可縮減的 Key）或最大誤差。僅處理全曲線為 Linear／Bezier 的通道，其他插值整條略過。

完成後 Ctrl+Z 復原。取消彈出窗不修改動畫。執行期間先在暫存場景處理曲線，全部完成後寫回；失敗時不留下部分結果。保留曲線修飾器、群組、Action Slot 與其他通道。鎖定曲線、唯讀 Action 略過。

多 Slot Action 依目前骨架使用中的 Slot、相同識別名稱或唯一相容 Object Slot 選取；仍不明確時略過，不會一律修改所有 Slot。共享 Action 的修改會影響其所有使用者。

安裝：Preferences → Extensions → Install from Disk，選擇 ZIP；或使用 Faidlix Blender Repository：
`https://raw.githubusercontent.com/Faidlix/BlenderAddons/main/repository/index.json`

授權 GPL-3.0-or-later。無其他 Faidlix 外掛相依。
