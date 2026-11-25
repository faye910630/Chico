using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// 泡泡射擊（夢幻甜點屋版）：Chico 在藍綠＋檸檬黃的甜點世界往上射泡泡，三顆以上同色就會破掉，
/// 沒有連到天花板的泡泡會一起掉下來。每射幾發天花板就往下壓一排，泡泡碰到底線就結束；清空整片就過關。
/// 操作：滑鼠瞄準、點一下發射；或 ← →／A D 調整彈道角度（虛線會顯示牆面反彈路徑）、空白鍵發射。Esc 離開。
/// </summary>
public class BubbleShooter : MonoBehaviour
{
    const float W = GameView.W, H = GameView.H;
    const float R = 8f;                    // 泡泡半徑（點陣格）
    const float RowH = 14f;                // 六角排列的行距（≈ R·√3）
    const int Cols = 15;                   // 偶數行 15 顆、奇數行（往右錯開半顆）14 顆
    const int MaxRows = 22;
    const float Top = H - 30f;             // 泡泡區的天花板（上面留給分數）
    const float DangerY = 78f;             // 泡泡中心低於這條線就輸了
    const float ShootX = W / 2f, ShootY = 46f;
    const float ShotSpeed = 380f;
    const int AimDotsN = 48;               // 瞄準虛線點數（含牆面反彈）
    const float AimStep = 6f;              // 虛線點距
    const float AimTurn = 140f;            // ← → 每秒轉角速度

    // 泡泡配色：跟甜點屋背景同一套藍綠／檸檬黃
    static readonly Color[] Colors =
    {
        Pix.C(52, 186, 176),    // 藍綠
        Pix.C(255, 226, 100),   // 檸檬黃
        Pix.C(120, 214, 200),   // 薄荷
        Pix.C(236, 196, 110),   // 蜜糖黃
        Pix.C(40, 140, 132),    // 深青綠
        Pix.C(255, 246, 170),   // 淺檸黃
    };

    class Row { public bool odd; public int[] c = new int[Cols]; public SpriteRenderer[] sr = new SpriteRenderer[Cols]; }
    class Fall { public float x, y, vx, vy; public SpriteRenderer sr; }
    class Fx { public float x, y, vx, vy, life; public SpriteRenderer sr; }
    class Rise { public float x, y, sp, ph; public SpriteRenderer sr; }

    readonly List<Row> rows = new List<Row>();
    readonly List<Fall> falls = new List<Fall>();
    readonly List<Fx> fxs = new List<Fx>();
    readonly List<Rise> rises = new List<Rise>();
    readonly List<SpriteRenderer> aimDots = new List<SpriteRenderer>();
    Sprite[] bubbleSprites;
    Transform world, boardT;
    Character her;
    SpriteRenderer tanuki, cur, next, shotSr;

    float aim = 90f;                       // 角度（度），90 = 正上方
    int curColor, nextColor;
    bool shooting;
    Vector2 shotPos, shotVel;
    int score, best, level = 1, shots, popped, dropEvery = 8, clears;
    bool over, cleared;
    float clearT, tanukiHop, t, autoT = 0.5f;
    string msg = "";
    float msgT;

    // ------------------------------------------------------------------ 初始化
    void Start()
    {
        var cam = Camera.main != null ? Camera.main : FindAnyObjectByType<Camera>();
        cam.backgroundColor = Pix.C(255, 236, 150);
        best = PlayerPrefs.GetInt("best_bubble", 0);
        world = new GameObject("World").transform;
        boardT = new GameObject("Board").transform;
        boardT.SetParent(world, false);
        bubbleSprites = new Sprite[Colors.Length];
        for (int i = 0; i < Colors.Length; i++) bubbleSprites[i] = MakeBubble(Colors[i]);
        BuildSweets();
        her = Character.Create(Boot.Outfit, world);
        her.transform.position = new Vector3(ShootX - 34, 16, 0);
        var tk = Resources.Load<Texture2D>("Pixel/tanuki");
        tanuki = Pix.Make("Tanuki", Pix.Load(tk != null ? "tanuki" : "pixel", new Vector2(0.5f, 0f)), 2, world);
        var launcher = Pix.Make("Launcher", MakeMacaron(), 1, world);
        launcher.transform.position = new Vector3(ShootX, ShootY - 14, 0);
        cur = Pix.Make("Current", bubbleSprites[0], 4, world);
        next = Pix.Make("Next", bubbleSprites[0], 4, world);
        shotSr = Pix.Make("Shot", bubbleSprites[0], 5, world);
        // 瞄準軌跡：用小圓點畫「會撞牆反彈」的路徑，藍綠／檸檬黃交替，才看得到
        var aimTeal = Pix.Circle(2, Pix.C(40, 120, 112), Pix.C(200, 246, 230));
        var aimYellow = Pix.Circle(2, Pix.C(201, 160, 20), Pix.C(255, 246, 200));
        for (int i = 0; i < AimDotsN; i++)
        {
            var d = Pix.Make("Aim", i % 2 == 0 ? aimTeal : aimYellow, 3, world);
            d.enabled = false;
            aimDots.Add(d);
        }
        var danger = Pix.Make("Danger", Pix.Dot, 0, world);
        danger.color = new Color(0.79f, 0.63f, 0.08f, 0.45f);
        danger.transform.position = new Vector3(W / 2, DangerY - R, 0);
        danger.transform.localScale = new Vector3(W, 1, 1);
        ResetGame();
    }

    void ResetGame()
    {
        foreach (var r in rows) ClearRow(r);
        rows.Clear();
        score = 0; level = 1; shots = 0; popped = 0; clears = 0; over = false; shooting = false;
        StartLevel();
    }

    void StartLevel()
    {
        foreach (var r in rows) ClearRow(r);
        rows.Clear();
        dropEvery = Mathf.Max(4, 9 - level);
        shots = 0;
        int nColors = Mathf.Min(Colors.Length, 3 + level);
        for (int i = 0; i < 5 + Mathf.Min(level, 4); i++) AddRowTop(nColors);
        curColor = PickColor();
        nextColor = PickColor();
        cleared = false;
        Say(level == 1 ? "來射泡泡吧！" : "第 " + level + " 關，加油！");
    }

    // ------------------------------------------------------------------ 夢幻甜點背景（藍綠＋檸檬黃）
    void BuildSweets()
    {
        // 漸層：上面藍綠、下面檸檬黃（每 4 格一層色帶）
        for (int y = 0; y < H; y += 4)
        {
            float k = y / H;
            var band = Pix.Make("Sky", Pix.Dot, -20, world);
            band.color = Color.Lerp(Pix.C(255, 236, 150), Pix.C(96, 196, 196), k);
            band.transform.position = new Vector3(W / 2, y + 2, 0);
            band.transform.localScale = new Vector3(W, 4, 1);
        }
        // 檸檬棉花糖雲
        var rng = new System.Random(5);
        for (int i = 0; i < 6; i++)
        {
            float cx = rng.Next(0, (int)W), cy = rng.Next(90, (int)H - 50);
            for (int k = 0; k < 3; k++)
            {
                var puff = Pix.Make("Cloud", Pix.Circle(6 + (k == 1 ? 2 : 0), new Color(1, 1, 0.98f, 0.8f), new Color(1, 0.96f, 0.75f, 0.8f)), -18, world);
                puff.transform.position = new Vector3(cx + (k - 1) * 10, cy + (k == 1 ? 3 : 0), 0);
            }
        }
        // 地面：檸檬沙＋藍綠糖霜（往下滴）
        var soil = Pix.Make("Cookie", Pix.Dot, -15, world);
        soil.color = Pix.C(236, 196, 110);
        soil.transform.position = new Vector3(W / 2, 8, 0);
        soil.transform.localScale = new Vector3(W, 16, 1);
        for (int x = 0; x < W; x += 2)
        {
            int drip = 2 + (int)(2 + 2 * Mathf.Sin(x * 0.45f)) + ((x * 7) % 23 < 4 ? 3 : 0);
            var icing = Pix.Make("Icing", Pix.Dot, -14, world);
            icing.color = Pix.C(96, 210, 196);
            icing.transform.position = new Vector3(x + 1, 16 - drip / 2f, 0);
            icing.transform.localScale = new Vector3(2, drip, 1);
        }
        for (int i = 0; i < 14; i++)
        {
            var chip = Pix.Make("Chip", Pix.Dot, -13, world);
            chip.color = Pix.C(70, 120, 110);
            chip.transform.position = new Vector3(rng.Next(2, (int)W - 2), rng.Next(2, 10), 0);
            chip.transform.localScale = new Vector3(2, 1, 1);
        }
        // 棒棒糖、拐杖糖（左右兩邊，不擋到發射台）
        Color[] pops = { Pix.C(52, 186, 176), Pix.C(255, 226, 100), Pix.C(120, 214, 200) };
        float[] px = { 14, 46, 206 };
        for (int i = 0; i < px.Length; i++)
        {
            int hgt = 22 + (i % 2) * 8;
            for (int y = 16; y < 16 + hgt; y++)
            {
                var stick = Pix.Make("Stick", Pix.Dot, -12, world);
                stick.color = Pix.C(255, 250, 220);
                stick.transform.position = new Vector3(px[i], y, 0);
            }
            var candy = Pix.Make("Lollipop", Pix.Circle(7, pops[i], Color.white), -11, world);
            candy.transform.position = new Vector3(px[i], 16 + hgt, 0);
        }
        foreach (float cx in new[] { 182f, 230f })
            for (int y = 16; y < 38; y++)
            {
                var cane = Pix.Make("Cane", Pix.Dot, -12, world);
                cane.color = ((y / 3) % 2 == 0) ? Pix.C(52, 170, 160) : Pix.C(255, 236, 120);
                cane.transform.position = new Vector3(cx, y, 0);
                cane.transform.localScale = new Vector3(2, 1, 1);
            }
        // 飄落的藍黃糖粒
        Color[] spr = { Pix.C(52, 186, 176), Pix.C(255, 226, 100), Pix.C(120, 214, 200), Pix.C(255, 246, 160), Pix.C(70, 160, 150) };
        for (int i = 0; i < 18; i++)
        {
            var b = Pix.Make("Sprinkle", Pix.Dot, -13, world);
            b.color = spr[i % spr.Length];
            b.transform.localScale = new Vector3(i % 2 == 0 ? 2 : 1, i % 2 == 0 ? 1 : 2, 1);
            rises.Add(new Rise { x = Random.Range(4f, W - 4), y = Random.Range(0f, H), sp = -Random.Range(10f, 22f),
                                 ph = Random.Range(0f, 6f), sr = b });
        }
    }

    // ------------------------------------------------------------------ 點陣圖（程式畫）
    static Sprite MakeBubble(Color c)
    {
        int d = 16;
        var tex = new Texture2D(d, d, TextureFormat.RGBA32, false) { filterMode = FilterMode.Point };
        var line = Color.Lerp(c, Color.black, 0.45f);
        var shade = Color.Lerp(c, Color.black, 0.15f);
        for (int y = 0; y < d; y++)
            for (int x = 0; x < d; x++)
            {
                float dx = x - 7.5f, dy = y - 7.5f;
                float r2 = dx * dx + dy * dy;
                Color o = Color.clear;
                if (r2 <= 7.6f * 7.6f) o = line;
                if (r2 <= 6.6f * 6.6f) o = (dx + dy > 4) ? c : (dx + dy < -6 ? shade : c);
                if (r2 <= 6.6f * 6.6f && dx - dy > 7) o = shade;
                // 高光（左上）
                if ((dx + 3) * (dx + 3) + (dy - 3) * (dy - 3) < 3.2f) o = Color.white;
                if ((dx - 3.5f) * (dx - 3.5f) + (dy + 3.5f) * (dy + 3.5f) < 1.1f && r2 < 40) o = Color.Lerp(c, Color.white, 0.6f);
                tex.SetPixel(x, y, o);
            }
        tex.Apply();
        return Sprite.Create(tex, new Rect(0, 0, d, d), new Vector2(0.5f, 0.5f), 1f);
    }

    static Sprite MakeMacaron()
    {
        // 發射台：藍綠／檸檬黃馬卡龍（上下兩片＋奶油夾心）
        int w = 30, h = 14;
        var tex = new Texture2D(w, h, TextureFormat.RGBA32, false) { filterMode = FilterMode.Point };
        var shell = Pix.C(96, 210, 196);
        var shellD = Pix.C(52, 170, 160);
        var cream = Pix.C(255, 246, 200);
        var line = Pix.C(28, 92, 96);
        for (int y = 0; y < h; y++)
            for (int x = 0; x < w; x++)
            {
                float dx = (x - 14.5f) / 15f, dy = (y - 6.5f) / 7f;
                bool inside = dx * dx * dx * dx + dy * dy * dy * dy <= 1f;
                bool edge = inside && dx * dx * dx * dx + dy * dy * dy * dy > 0.7f;
                Color c = Color.clear;
                if (inside) c = (y == 6 || y == 7) ? cream : (y == 5 || y == 8 ? shellD : shell);
                if (edge) c = line;
                if (inside && !edge && y == 11 && x > 6 && x < 12) c = Color.white;  // 光澤
                tex.SetPixel(x, y, c);
            }
        tex.Apply();
        return Sprite.Create(tex, new Rect(0, 0, w, h), new Vector2(0.5f, 0f), 1f);
    }

    // ------------------------------------------------------------------ 格子
    int RowCols(Row r) => r.odd ? Cols - 1 : Cols;

    Vector2 Center(int row, int col)
    {
        var r = rows[row];
        return new Vector2(R + col * 2 * R + (r.odd ? R : 0), Top - R - row * RowH);
    }

    bool Valid(int row, int col) => row >= 0 && row < rows.Count && col >= 0 && col < RowCols(rows[row]);

    int Get(int row, int col) => Valid(row, col) ? rows[row].c[col] : -1;

    IEnumerable<Vector2Int> Neighbors(int row, int col)
    {
        yield return new Vector2Int(row, col - 1);
        yield return new Vector2Int(row, col + 1);
        bool odd = rows[row].odd;
        int a = odd ? col : col - 1, b = odd ? col + 1 : col;
        foreach (int dr in new[] { -1, 1 })
        {
            yield return new Vector2Int(row + dr, a);
            yield return new Vector2Int(row + dr, b);
        }
    }

    void ClearRow(Row r)
    {
        foreach (var s in r.sr) if (s) Destroy(s.gameObject);
    }

    Row NewRow(bool odd)
    {
        var r = new Row { odd = odd };
        for (int i = 0; i < Cols; i++) r.c[i] = -1;
        return r;
    }

    void AddRowTop(int nColors)
    {
        bool odd = rows.Count > 0 ? !rows[0].odd : false;
        var r = NewRow(odd);
        for (int i = 0; i < RowCols(r); i++) r.c[i] = Random.Range(0, nColors);
        rows.Insert(0, r);
        while (rows.Count > MaxRows) { ClearRow(rows[rows.Count - 1]); rows.RemoveAt(rows.Count - 1); }
        SyncSprites();
    }

    void EnsureRow(int row)
    {
        while (rows.Count <= row) rows.Add(NewRow(!rows[rows.Count - 1].odd));
    }

    void SyncSprites()
    {
        for (int ri = 0; ri < rows.Count; ri++)
        {
            var r = rows[ri];
            for (int c = 0; c < Cols; c++)
            {
                int v = c < RowCols(r) ? r.c[c] : -1;
                if (v < 0)
                {
                    if (r.sr[c]) { Destroy(r.sr[c].gameObject); r.sr[c] = null; }
                    continue;
                }
                if (!r.sr[c]) r.sr[c] = Pix.Make("Bubble", bubbleSprites[v], 2, boardT);
                r.sr[c].sprite = bubbleSprites[v];
                var p = Center(ri, c);
                r.sr[c].transform.position = new Vector3(Mathf.Round(p.x), Mathf.Round(p.y), 0);
            }
        }
    }

    int PickColor()
    {
        var present = new List<int>();
        foreach (var r in rows)
            for (int i = 0; i < RowCols(r); i++)
                if (r.c[i] >= 0 && !present.Contains(r.c[i])) present.Add(r.c[i]);
        if (present.Count == 0) return Random.Range(0, Mathf.Min(Colors.Length, 3 + level));
        return present[Random.Range(0, present.Count)];
    }

    bool BoardEmpty()
    {
        foreach (var r in rows)
            for (int i = 0; i < RowCols(r); i++)
                if (r.c[i] >= 0) return false;
        return true;
    }

    // ------------------------------------------------------------------ 每格更新
    void Update()
    {
        if (GameInput.Escape) Application.Quit();
        float dt = Mathf.Min(Time.deltaTime, 1f / 20f);
        t += dt;
        msgT -= dt;
        her.Squash = Mathf.Max(0, her.Squash - dt * 4);
        tanukiHop = Mathf.Max(0, tanukiHop - dt * 3);
        UpdateFx(dt);
        if (over)
        {
            if (GameInput.ConsumeClick()) ResetGame();
        }
        else if (cleared)
        {
            GameInput.ConsumeClick();
            clearT -= dt;
            if (clearT <= 0) { level++; StartLevel(); }
        }
        else Step(dt);
        Draw();
    }

    void Step(float dt)
    {
        // 瞄準：← →／A D 調角度（彈道虛線會跟著變）；沒按鍵時跟滑鼠
        int dx = GameInput.Dx;
        if (dx != 0) aim = Mathf.Clamp(aim - dx * AimTurn * dt, 12f, 168f);
        else if (GameInput.MouseX.HasValue && GameInput.MouseY.HasValue)
        {
            float ax = GameInput.MouseX.Value - ShootX, ay = Mathf.Max(4f, GameInput.MouseY.Value - ShootY);
            aim = Mathf.Clamp(Mathf.Atan2(ay, ax) * Mathf.Rad2Deg, 12f, 168f);
        }
        bool click = GameInput.ConsumeClick();
        if (Boot.AutoPlay && !shooting)
        {
            autoT -= dt;
            if (autoT <= 0) { aim = Random.Range(40f, 140f); click = true; autoT = 0.35f; }
        }
        her.Face = aim < 70 ? 1 : (aim > 110 ? -1 : 0);
        if (!shooting && click)
        {
            float a = aim * Mathf.Deg2Rad;
            shotVel = new Vector2(Mathf.Cos(a), Mathf.Sin(a)) * ShotSpeed;
            shotPos = new Vector2(ShootX, ShootY);
            shooting = true;
            shotSr.sprite = bubbleSprites[curColor];
            curColor = nextColor;
            nextColor = PickColor();
            her.Squash = 0.7f;
        }
        if (shooting) MoveShot(dt);
    }

    void MoveShot(float dt)
    {
        float dist = ShotSpeed * dt;
        int steps = Mathf.CeilToInt(dist / 2f);
        for (int i = 0; i < steps; i++)
        {
            shotPos += shotVel * (dt / steps);
            if (shotPos.x < R) { shotPos.x = R; shotVel.x = Mathf.Abs(shotVel.x); }
            if (shotPos.x > W - R) { shotPos.x = W - R; shotVel.x = -Mathf.Abs(shotVel.x); }
            if (shotPos.y >= Top - R || Touching(shotPos))
            {
                Land();
                return;
            }
        }
    }

    bool Touching(Vector2 p)
    {
        for (int ri = 0; ri < rows.Count; ri++)
        {
            float cy = Top - R - ri * RowH;
            if (Mathf.Abs(cy - p.y) > 2 * R) continue;
            var r = rows[ri];
            for (int c = 0; c < RowCols(r); c++)
                if (r.c[c] >= 0 && (Center(ri, c) - p).sqrMagnitude < (2 * R * 0.86f) * (2 * R * 0.86f))
                    return true;
        }
        return false;
    }

    void Land()
    {
        shooting = false;
        int color = System.Array.IndexOf(bubbleSprites, shotSr.sprite);
        // 找離落點最近的空格（必須貼著天花板或別的泡泡）
        int estRow = Mathf.Clamp(Mathf.RoundToInt((Top - R - shotPos.y) / RowH), 0, MaxRows - 1);
        EnsureRow(Mathf.Min(MaxRows - 1, estRow + 1));
        float bestD = float.MaxValue;
        Vector2Int bestCell = new Vector2Int(-1, -1);
        for (int ri = Mathf.Max(0, estRow - 1); ri <= Mathf.Min(rows.Count - 1, estRow + 1); ri++)
            for (int c = 0; c < RowCols(rows[ri]); c++)
            {
                if (rows[ri].c[c] >= 0) continue;
                bool attached = ri == 0;
                foreach (var n in Neighbors(ri, c)) if (Get(n.x, n.y) >= 0) { attached = true; break; }
                if (!attached) continue;
                float d = (Center(ri, c) - shotPos).sqrMagnitude;
                if (d < bestD) { bestD = d; bestCell = new Vector2Int(ri, c); }
            }
        if (bestCell.x < 0)
        {
            // 理論上不會發生；保險：放在最近的空格
            for (int ri = 0; ri < rows.Count; ri++)
                for (int c = 0; c < RowCols(rows[ri]); c++)
                    if (rows[ri].c[c] < 0)
                    {
                        float d = (Center(ri, c) - shotPos).sqrMagnitude;
                        if (d < bestD) { bestD = d; bestCell = new Vector2Int(ri, c); }
                    }
        }
        rows[bestCell.x].c[bestCell.y] = color;
        SyncSprites();

        var group = Flood(bestCell, color);
        if (group.Count >= 3)
        {
            foreach (var g in group)
            {
                var p = Center(g.x, g.y);
                Burst(p.x, p.y, Colors[rows[g.x].c[g.y]]);
                rows[g.x].c[g.y] = -1;
            }
            int n = group.Count;
            score += n * 10;
            popped += n;
            int dropped = DropFloating();
            score += dropped * 20;
            tanukiHop = 1f;
            if (n + dropped >= 6) Say(n + dropped >= 10 ? "哇～好多泡泡！" : "啵啵啵！");
            SyncSprites();
        }
        else
        {
            shots++;
            if (shots >= dropEvery)
            {
                shots = 0;
                AddRowTop(Mathf.Min(Colors.Length, 3 + level));
                Say("天花板下來了！小心～");
            }
        }
        TrimRows();
        if (BoardEmpty())
        {
            score += 500;
            clears++;
            cleared = true;
            clearT = 2.0f;
            her.Squash = 1f;
            tanukiHop = 1f;
            Say("全部清空！ +500");
            return;
        }
        if (LowestY() < DangerY) GameOver();
    }

    List<Vector2Int> Flood(Vector2Int start, int color)
    {
        var res = new List<Vector2Int>();
        var seen = new HashSet<Vector2Int> { start };
        var q = new Queue<Vector2Int>();
        q.Enqueue(start);
        while (q.Count > 0)
        {
            var p = q.Dequeue();
            res.Add(p);
            foreach (var n in Neighbors(p.x, p.y))
                if (!seen.Contains(n) && Get(n.x, n.y) == color) { seen.Add(n); q.Enqueue(n); }
        }
        return res;
    }

    int DropFloating()
    {
        var seen = new HashSet<Vector2Int>();
        var q = new Queue<Vector2Int>();
        if (rows.Count > 0)
            for (int c = 0; c < RowCols(rows[0]); c++)
                if (rows[0].c[c] >= 0) { var p = new Vector2Int(0, c); seen.Add(p); q.Enqueue(p); }
        while (q.Count > 0)
        {
            var p = q.Dequeue();
            foreach (var n in Neighbors(p.x, p.y))
                if (!seen.Contains(n) && Get(n.x, n.y) >= 0) { seen.Add(n); q.Enqueue(n); }
        }
        int count = 0;
        for (int ri = 0; ri < rows.Count; ri++)
            for (int c = 0; c < RowCols(rows[ri]); c++)
                if (rows[ri].c[c] >= 0 && !seen.Contains(new Vector2Int(ri, c)))
                {
                    var pos = Center(ri, c);
                    var sr = Pix.Make("Fall", bubbleSprites[rows[ri].c[c]], 3, world);
                    falls.Add(new Fall { x = pos.x, y = pos.y, vx = Random.Range(-30f, 30f), vy = Random.Range(20f, 60f), sr = sr });
                    rows[ri].c[c] = -1;
                    count++;
                }
        return count;
    }

    void TrimRows()
    {
        while (rows.Count > 1)
        {
            var r = rows[rows.Count - 1];
            bool empty = true;
            for (int i = 0; i < RowCols(r); i++) if (r.c[i] >= 0) { empty = false; break; }
            if (!empty) break;
            ClearRow(r);
            rows.RemoveAt(rows.Count - 1);
        }
    }

    float LowestY()
    {
        float y = H;
        for (int ri = 0; ri < rows.Count; ri++)
            for (int c = 0; c < RowCols(rows[ri]); c++)
                if (rows[ri].c[c] >= 0) y = Mathf.Min(y, Top - R - ri * RowH);
        return y;
    }

    void GameOver()
    {
        over = true;
        best = Mathf.Max(best, score);
        PlayerPrefs.SetInt("best_bubble", best);
        PlayerPrefs.Save();
        GameResult.Add("bubble", score, popped, clears > 0);
        Say("哎呀，泡泡太多了～");
    }

    void Say(string s) { msg = s; msgT = 1.8f; }

    // ------------------------------------------------------------------ 特效
    void Burst(float bx, float by, Color c)
    {
        for (int i = 0; i < 5; i++)
        {
            float a = Random.Range(0f, Mathf.PI * 2);
            var sr = Pix.Make("Fx", Pix.Dot, 6, world);
            sr.color = i % 2 == 0 ? c : Color.white;
            fxs.Add(new Fx { x = bx, y = by, vx = Mathf.Cos(a) * 45, vy = Mathf.Sin(a) * 45, life = 0.4f, sr = sr });
        }
    }

    void UpdateFx(float dt)
    {
        fxs.RemoveAll(f =>
        {
            f.life -= dt;
            f.x += f.vx * dt;
            f.y += f.vy * dt;
            f.vy -= 40 * dt;
            f.sr.transform.position = new Vector3(Mathf.Round(f.x), Mathf.Round(f.y), 0);
            if (f.life > 0) return false;
            Destroy(f.sr.gameObject);
            return true;
        });
        falls.RemoveAll(f =>
        {
            f.vy -= 420 * dt;
            f.x += f.vx * dt;
            f.y += f.vy * dt;
            f.sr.transform.position = new Vector3(Mathf.Round(f.x), Mathf.Round(f.y), 0);
            if (f.y > -10) return false;
            Destroy(f.sr.gameObject);
            return true;
        });
        foreach (var b in rises)
        {
            b.y += b.sp * dt;
            if (b.y > H + 4) { b.y = -4; b.x = Random.Range(4f, W - 4); }
            if (b.y < 14) { b.y = H + 2; b.x = Random.Range(4f, W - 4); }
            b.sr.transform.position = new Vector3(Mathf.Round(b.x + Mathf.Sin(t * 2 + b.ph) * 2), Mathf.Round(b.y), 0);
        }
    }

    // ------------------------------------------------------------------ 繪製
    void Draw()
    {
        // 瞄準軌跡：模擬真實彈道（左右牆反彈），直到碰到泡泡或天花板
        bool showAim = !over && !cleared && !shooting;
        float a = aim * Mathf.Deg2Rad;
        Vector2 p = new Vector2(ShootX, ShootY);
        Vector2 v = new Vector2(Mathf.Cos(a), Mathf.Sin(a));
        for (int i = 0; i < aimDots.Count; i++)
        {
            p += v * AimStep;
            // 與實際發射相同的牆面反彈
            if (p.x < R) { p.x = 2 * R - p.x; v.x = -v.x; }
            if (p.x > W - R) { p.x = 2 * (W - R) - p.x; v.x = -v.x; }
            bool on = showAim && p.y < Top - R && p.y > 8f && !Touching(p);
            aimDots[i].enabled = on;
            if (!on)
            {
                for (int k = i + 1; k < aimDots.Count; k++) aimDots[k].enabled = false;
                break;
            }
            // 閃爍透明度，讓軌跡更像虛線
            float pulse = ((i + (int)(t * 10)) % 4 == 0) ? 0.45f : 1f;
            var c = aimDots[i].color;
            c.a = pulse;
            aimDots[i].color = c;
            aimDots[i].transform.position = new Vector3(Mathf.Round(p.x), Mathf.Round(p.y), 0);
        }
        cur.sprite = bubbleSprites[curColor];
        cur.enabled = !shooting && !over;
        cur.transform.position = new Vector3(ShootX, ShootY, 0);
        next.sprite = bubbleSprites[nextColor];
        next.transform.position = new Vector3(ShootX + 40, 22, 0);
        next.transform.localScale = new Vector3(0.75f, 0.75f, 1);
        shotSr.enabled = shooting;
        if (shooting) shotSr.transform.position = new Vector3(Mathf.Round(shotPos.x), Mathf.Round(shotPos.y), 0);
        float hop = Mathf.Sin(tanukiHop * Mathf.PI) * 8;
        tanuki.transform.position = new Vector3(ShootX + 64, 16 + Mathf.Round(hop), 0);
        her.transform.position = new Vector3(ShootX - 40, 16, 0);
    }

    void OnGUI()
    {
        float z = Screen.height / H;
        int fs = Mathf.RoundToInt(11 * z);
        var uiFill = Pix.C(255, 249, 224);
        var uiLine = Pix.C(58, 168, 154);
        var uiText = Pix.C(31, 95, 90);
        var uiHi = Pix.C(201, 160, 20);
        Pix.Box(new Rect(2 * z, 2 * z, 96 * z, 24 * z), uiFill, uiLine);
        GUI.Label(new Rect(6 * z, 3 * z, 300, 40), "分數 " + score, Pix.Label(fs, uiText));
        GUI.Label(new Rect(6 * z, 13 * z, 300, 40), "最佳 " + best, Pix.Label(fs, uiText));
        GUI.Label(new Rect((W - 60) * z, 6 * z, 200, 40), "第 " + level + " 關", Pix.Label(fs, uiText));
        GUI.Label(new Rect((ShootX + 26) * z, (H - 40) * z, 200, 40), "下一顆", Pix.Label(Mathf.RoundToInt(9 * z), uiText));
        GUI.Label(new Rect(6 * z, (H - 14) * z, 400, 40), "← → 調路徑・點一下發射", Pix.Label(Mathf.RoundToInt(9 * z), uiHi));
        // 天花板還有幾發會下降
        int left = dropEvery - shots;
        for (int i = 0; i < dropEvery; i++)
        {
            var c = i < left ? Pix.C(52, 186, 176) : Pix.C(200, 239, 230);
            Pix.Box(new Rect((W - 8 - i * 7) * z, 20 * z, 5 * z, 4 * z), c, c);
        }
        if (msgT > 0 && !over)
        {
            var st = Pix.Label(fs, uiHi);
            st.alignment = TextAnchor.MiddleCenter;
            GUI.Label(new Rect(0, (H / 2 - 20) * z, W * z, 30 * z), msg, st);
        }
        if (over)
        {
            Pix.Box(new Rect(14 * z, (H / 2 - 40) * z, (W - 28) * z, 80 * z), uiFill, uiLine);
            GUI.Label(new Rect(24 * z, (H / 2 - 34) * z, 400, 40), "哎呀，泡泡太多了～", Pix.Label(fs, uiText));
            GUI.Label(new Rect(24 * z, (H / 2 - 18) * z, 400, 40), "分數 " + score + "（打破 " + popped + " 顆）", Pix.Label(fs, uiHi));
            GUI.Label(new Rect(24 * z, (H / 2 - 2) * z, 400, 40), "最佳 " + best, Pix.Label(fs, uiText));
            GUI.Label(new Rect(24 * z, (H / 2 + 16) * z, 400, 40), "空白鍵／點一下：再玩", Pix.Label(fs, uiText));
        }
    }
}
