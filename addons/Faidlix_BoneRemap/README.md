# Faidlix Bone Remap

Blender 4.5+ 批次骨架動畫重定向外掛。

## 安裝

1. 在 Blender 開啟 `Edit > Preferences > Get Extensions`.
2. 右上角選單選擇 `Repositories > Add Remote Repository`.
3. 貼上：
   `https://raw.githubusercontent.com/Faidlix/BlenderAddons/main/repository/index.json`
4. 搜尋 `Faidlix Bone Remap` 並安裝。

安裝後位於 `3D Viewport > Sidebar > Faidlix > Faidlix_Retarget Motion`。

介面配置遵循 [DESIGN.md](DESIGN.md)。

## 功能

- 主要骨架從場景骨架下拉選擇，並追蹤目前選取骨架。
- 批次匯入 FBX、GLB、GLTF 與 BLEND。
- 可直接選取整個資料夾，遞迴加入所有子資料夾內的支援檔案。
- 匯入來源放入隱藏暫存集合；非骨架物件立即移除，Bake 完成後保留來源，只有按下「全部清空動畫檔」或「全部重設」才清除。
- 同一骨架內的多個 Action 全部收集。
- 自動對應會把縮放套用到實際來源 Armature，並依角色前方與每根骨頭 Rest Pose／Bone Roll 進行 Quaternion 換基底；Object、Pose、Edit Mode 尺寸一致。
- T-Pose 與動畫預覽會保留目前模式；動畫預覽同步顯示來源原始 Action 與 Target 重新定向結果。
- 可為已映射或未指定的骨頭建立非 Deform IK 控制骨，形狀、大小、線框粗細與顏色會即時預覽，且不受骨長縮放；未指定骨頭不寫入重定向動畫。
- IK 設定直接展開於外掛側邊欄，樣式為可見文字按鈕；關閉設定時還原開啟前選取的骨架與模式。
- 目標動畫清單位於批次重定向按鈕下方；播放單段動畫時，場景 Start／End 同步切換至該 Action 的影格範圍。
- 動畫與骨骼對應清單提供共用欄寬調整；複數動畫子列會釋放空白檔名區，保留動畫名稱與時間可讀性。
- 全部重設會移除此外掛建立的 IK 控制骨、約束、隱藏形狀物件、Mesh 與專用集合。
- 骨名、數量與父子結構相同時，自動沿用映射組、實際縮放、角色前方與 Action Slot 綁定；Rest 軸向差異可另外人工修正。
- 每段可設原地動畫、只輸出左右翻轉，或同時輸出原版與翻轉版。
- 每段獨立 Action，或指定起始與間隔合併成長 Action。
- 每格 Bake、只保留來源 Key，或 Bake 後依誤差精簡。
- 以可取消的背景分段方式 Bake，完成時顯示訊息，並自動設定輸出 Action 與 Action Slot。
- Fake User 預設開啟，支援 Extract Root Motion 與 Root 位移縮放。
- 介面頂部提供「全部重設」與 GitHub「線上更新」。

## 開發驗證

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' --background --factory-startup --python .\tests\test_headless.py
& 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' --background --factory-startup --python .\tests\test_blend_import.py
```
