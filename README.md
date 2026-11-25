# Chico 點陣桌寵

以「朵莉姆桌寵」（`dream-god-desktop-pet/l2d_pet.pyw`）為底改編，角色換成 Chico：薄荷綠頭髮、開朗愛笑，她的元素是甜點，住在夢幻甜點屋，最好的朋友是小狸貓。

`preview/` 裡的 PSD（洋裝、水手服各 8 視角，小狸貓 8 視角）自動點陣化成 75×75 點陣，顯示為 **130×130 px**。畫風、服裝照原圖，只做點陣化；每個視角內部的縫隙都會補滿，轉身時不會出現破洞。

## 啟動

雙擊 `啟動桌寵.bat`，或：

```powershell
pythonw chico_pet.pyw
```

需要 `pip install numpy pillow scipy`；第一次執行會用 `psd-tools` 把 PSD 拆成 `assets/layers/` 的 PNG。PSD 改過後執行 `python chico_pet.pyw --export` 重新拆圖層。

## 功能

- **桌面上的 Chico**：走路、彈跳、轉圈、前空翻、側翻、倒吊、爬視窗、跌倒、跟著滑鼠走、拖曳甩動
- **視線**：眼睛（只有虹膜）跟著滑鼠上下左右看、會眨眼、睡覺閉眼；滑鼠很遠時整個人轉向斜側
- **不抖動**：不做分區塊的像素變形（呼吸、頭擺、頭髮物理），整個人一起動，不會破圖
- **扔零食**：邊走邊往身後扔棒棒糖、餅乾、蛋糕、甜甜圈；點一下收掉，10 分鐘後消失
- **小狸貓**：抱抱（兩隻袖子圈住、瞇眼左右搖、冒愛心）、拋高高（拋三次接住，最後丟到旁邊，會邊飛邊轉）、用滑鼠抓起來甩
- **照顧**：飽食／清潔／心情／體力；餵食（隨機：糖果、餅乾、蛋糕、馬卡龍，一口一口吃掉）、泡泡澡、睡覺（湖水綠的小狸貓床）
- **對話**：開朗、三句不離甜點
- **跳舞**：配原創舞曲「草莓糖霜波卡」（132 BPM，程式合成）
- **換裝**：洋裝／水手服
- **夢幻甜點屋**（雙擊她）：藍綠天空、檸檬黃雲與糖粒；檸檬起司小屋（藍綠糖霜屋頂、檸檬頂飾、藍黃拐杖糖煙囪、發光圓窗、藍綠門、藍黃馬卡龍台階）、棒棒糖樹、軟糖；狀態條、按鈕、RPG 對話（洋裝正面的點陣半身立繪）。按鈕、輸入框、對話框、說話泡泡全部是 Cubic 11 點陣字（原生 11px × 2）＋點陣框；視窗／捷徑圖示是小狸貓
- **小遊戲**（Unity + C#）：
  - 泡泡射擊：藍綠＋檸檬黃甜點世界裡射泡泡（馬卡龍發射台）；虛線顯示牆面反彈彈道，← →／A D 可調路徑，三顆同色破掉、懸空的會掉下來，天花板每幾發往下壓一排，清空過關
  - 接點心：藍綠檸檬天空，接棒棒糖、糖果、餅乾、蛋糕、甜甜圈、馬卡龍（無生命、無星星，漏接不算輸，Esc 離開）
- 開機自動啟動、聲音開關

## Unity 小遊戲

專案在 `unity/ChicoGames`（Unity 6000.6.10f1），建置結果在 `unity/Build/ChicoGames.exe`。桌寵開小遊戲時會帶入目前的衣服，關掉後讀成績加心情。

```powershell
python chico_pet.pyw --export-unity
& "C:\Program Files\Unity\Hub\Editor\6000.6.10f1\Editor\Unity.exe" -batchmode -quit -projectPath unity\ChicoGames -executeMethod BuildScript.Build -logFile unity\build.log
```

也可以在 Unity 編輯器選單 **Chico → Build Windows** 建置。啟動參數：`-game bubble|stars`、`-outfit N`、`-result 成績.json`；測試用 `-autoplay`（自動射泡泡）、`-shot 截圖.png -shotdelay 秒`。

## 檔案

```
chico_pet.pyw        桌寵主程式（改編自 l2d_pet.pyw）
sprites.py           拆 PSD、點陣化、補洞、眼睛（虹膜位移／眨眼）、小狸貓、零食點陣圖
assets/layers/       從 PSD 拆出的圖層（自動產生）
unity/ChicoGames/    Unity 小遊戲專案（BubbleShooter.cs、StarCatch.cs…）
unity/Build/         建置好的小遊戲
fonts/               點陣字型 Cubic 11（OFL）
```

存檔與錯誤記錄在 `%APPDATA%\ChicoPet\`。測試：`python chico_pet.pyw --demo out.gif` 不開視窗輸出示範動畫；`--do 動作` 啟動後直接做某個動作。

## 打包 exe

\\\powershell
.\build_chico_exe.bat
\\\

產出在 \dist\Chico\Chico.exe\（旁邊的 \unity\Build\ 是小遊戲）。GitHub Release 附 Windows 壓縮包。

