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
- 自動對應、骨架預覽縮放對位、左右映射、來源 Rest Pose／軸向與位置倍率校正。
- 可為已映射或未指定的骨頭建立非 Deform IK 控制骨，球形等樣式與大小會即時預覽；未指定骨頭不寫入重定向動畫。
- 骨名、數量與父子結構相同時，自動沿用映射組；Rest 軸向差異另外提示及修正。
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
