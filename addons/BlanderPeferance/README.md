# Blander Peferance

開啟 `.blend` 檔案時，預設保留使用者目前的 Blender 介面，不讀取檔案內儲存的工作區與介面配置。

## 行為

- 啟用外掛時，自動關閉 Blender 的「讀取 UI」預設值。
- 每次載入檔案後，再把下一次開啟檔案的預設值恢復為關閉。
- 若某個檔案確實需要自己的介面，仍可在開啟檔案視窗手動勾選「讀取 UI」；該次載入不受阻止。
- 不修改模型、材質、場景或其他 Blender 偏好設定。

## 手動確認

在「編輯 > 偏好設定 > 儲存與載入」中，可確認「載入 UI」維持未勾選。

## Blender 5.2 偏好設定備份

`preferences_backup/Blender-5.2-userpref.blend` 是建立此外掛時的 Blender 5.2 偏好設定備份。
還原前請先備份自己現有的 `userpref.blend`，並只在相同 Blender 版本中使用。
