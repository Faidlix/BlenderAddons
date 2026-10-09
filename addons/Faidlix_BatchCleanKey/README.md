# Faidlix_BatchCleanKey 1.2.0

每列 Action 在複製按鈕前新增循環按鈕。彈窗確認後，以目前骨架 Slot 中所有有 Key 曲線的最早／最晚影格為共同範圍，較短曲線補上頭尾 Key，尾端值接回開頭。預設銜接斜率，採開頭斜率設定頭尾 Free 控制柄，並將接縫鄰接段設為 Bezier；可取消勾選以只對齊頭尾值。保留範圍內 Key 的位置與值；接縫附近動作可能改變。多層、鎖定／停用、修飾器或 Sampled 曲線需先整理／烘焙。整個操作可 Ctrl+Z 復原。

Action 切換清單使用 Blender 原生可編輯名稱欄位：單擊選取並切換 Action，雙擊名稱進入改名。選取時同步場景時間軸 Start／End，優先採 Action 的手動範圍，否則採實際 Key／取樣曲線範圍；小數起訖向外取整，空 Action 為 1–1。不改變目前影格。

新增「批次轉換旋轉 Key」彈窗，沿用骨骼與 Action 多選，可將 Quaternion（WXYZ）與 XYZ Euler 雙向換算。保留原始 Key 的影格位置，並按烘焙間隔補取樣；預設每 1 影格。取樣點的局部旋轉相同，點間採 Linear（全來源通道 Constant 時保留 Constant），因此點間動畫為近似；較小間隔可提高子影格精度。Euler 使用相容角度保持連續，Quaternion 使用同半球符號避免跳轉。

轉換會切換骨骼的全域旋轉模式。未勾選 Action 若仍有所選骨骼的來源旋轉曲線，會提示一併勾選並中止，不擅自修改未選 Action。來源需完整 4／3 通道；唯讀、Slot 不明確、多層、Driver、鎖定／停用、修飾器、Sampled 曲線、非 Constant 外插或已有目標旋轉通道會中止，請先整理或烘焙。只修改所選骨骼的旋轉通道，保留其他骨骼、位置、縮放與其他 Slot。共享 Action 仍影響其所有使用者。進度、Esc 取消、全部成功才寫回及 Ctrl+Z 復原與原批次工具相同。

Blender 5.2+ 獨立 Extension。Pose Mode 選取骨骼後，在 3D View、Dope Sheet、Action Editor 或 Graph Editor 的 N 側邊欄 → Faidlix → Faidlix_BatchCleanKey → 批次處理 Action Keys。

彈出窗：單擊 Action 單選；Ctrl+單擊增選／減選；Shift+單擊選取錨點至目前列的範圍；Ctrl+Shift 加入範圍。提供全選與取消全選。Action 清單按名稱排序，顯示所選骨骼的 Key 數量，預選目前 Action。

骨骼清單與批次 Action 清單皆可摺疊，固定高度搭配捲軸，無換頁。骨骼清單列出目前骨架所有骨骼，名稱前的勾選框與 Pose Mode 選取雙向同步；更改骨骼選取會更新各 Action 的 Key 數量與處理範圍。

3D View 預設展開獨立的 Action 切換清單。最上方「同步所有 Action 影格範圍」依實際 Key／取樣曲線起訖設定各 Action 的手動影格範圍，不移動或縮放 Key；空白與唯讀 Action 略過。其下並排「新增 Action」「刪除 Action」。點名稱切換目前骨架的 Action，並高亮目前項目。刪除會刪除整個 Action 資料並解除所有使用者連結，可 Undo。

每列名稱後有複製與左右翻轉按鈕。複製建立獨立副本並切換；翻轉彈窗選擇「建立翻轉副本」或「修改原 Action」。採 Blender Paste Flipped 的骨架局部 X 軸規則、Blender 左右名稱配對；保留 Key 時間、控制柄與插值。中線骨骼也會鏡像，找不到對側骨骼的通道保留。需反號而含修飾器／取樣的通道需先烘焙為 Key，以免無法正確鏡像。物件自身通道與其他 Slot 保留。新增和複製 Action 啟用 Fake User，以便存檔保留。

- Delete：移除所選骨骼全部 Key，保留空通道與 Action、其他骨骼及物件通道。
- Clean：使用 Blender 原生 Clean，設定閾值。它會依 Blender 規則調整控制柄，請檢查動畫結果。
- Decimate：使用 Blender 原生縮減，支援移除比例（0.5 = 移除約一半可縮減的 Key）或最大誤差。僅處理全曲線為 Linear／Bezier 的通道，其他插值整條略過。

完成後 Ctrl+Z 復原。取消彈出窗不修改動畫。執行期間先在暫存場景處理曲線，全部完成後寫回；失敗時不留下部分結果。保留曲線修飾器、群組、Action Slot 與其他通道。鎖定曲線、唯讀 Action 略過。

批次運算以分段 modal 流程執行，編輯器浮層與側邊欄顯示進度百分比、目前 Action 及已完成／總通道數。Esc 取消且保留原動畫。全部運算成功後才一次寫回，完成操作支援 Undo。

多 Slot Action 依目前骨架使用中的 Slot、相同識別名稱或唯一相容 Object Slot 選取；仍不明確時略過，不會一律修改所有 Slot。共享 Action 的修改會影響其所有使用者。

安裝：Preferences → Extensions → Install from Disk，選擇 ZIP；或使用 Faidlix Blender Repository：
`https://raw.githubusercontent.com/Faidlix/BlenderAddons/main/repository/index.json`

授權 GPL-3.0-or-later。無其他 Faidlix 外掛相依。
