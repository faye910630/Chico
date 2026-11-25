using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// 接點心：藍綠＋檸檬黃天空裡左右移動接住落下的棒棒糖、糖果、餅乾、蛋糕、甜甜圈、馬卡龍（+1）。
/// 沒有生命、沒有星星；漏接只是沒分數，可一直玩，Esc 離開並記錄成績。
/// </summary>
public class StarCatch : MonoBehaviour
{
    const float W = GameView.W, H = GameView.H;
    const float Floor = 30f;   // 地面高度（從畫面底部往上）
    const float Speed = 150f;
    const float Catch = 20f;   // 左右接得到的範圍
    const float BodyH = 58f;   // 身體高度（接點心的判定）

    static readonly string[] Snacks = { "lollipop", "cookie", "cake", "donut", "candy", "macaron" };

    class Obj { public float x, y, vy, vx, ph; public string kind; public SpriteRenderer sr; }
    class Fx { public float x, y, vx, vy, life; public SpriteRenderer sr; }

    readonly List<Obj> objs = new List<Obj>();
    readonly List<Fx> fxs = new List<Fx>();
    float x, vx, t, spawnT, hurt;
    int score, best;
    bool saved;
    Character her;
    Transform world;

    void Start()
    {
        var cam = Camera.main != null ? Camera.main : FindAnyObjectByType<Camera>();
        cam.backgroundColor = Pix.C(255, 236, 150);
        best = PlayerPrefs.GetInt("best_stars", 0);
        world = new GameObject("World").transform;
        // 夢幻漸層：上面藍綠、中間薄荷、下面檸檬黃（每 4 格一層色帶）
        for (int y = 0; y < H; y += 4)
        {
            float k = y / H;
            Color c = k > 0.5f ? Color.Lerp(Pix.C(150, 214, 206), Pix.C(96, 196, 196), (k - 0.5f) * 2)
                               : Color.Lerp(Pix.C(255, 236, 150), Pix.C(150, 214, 206), k * 2);
            var band = Pix.Make("Sky", Pix.Dot, -20, world);
            band.color = c;
            band.transform.position = new Vector3(W / 2, y + 2, 0);
            band.transform.localScale = new Vector3(W, 4, 1);
        }
        // 檸檬棉花糖雲
        var rng = new System.Random(9);
        for (int i = 0; i < 7; i++)
        {
            float cx = rng.Next(0, (int)W), cy = rng.Next(80, (int)H - 30);
            for (int k = 0; k < 4; k++)
            {
                var puff = Pix.Make("Cloud", Pix.Circle(6 + k % 2 * 2, new Color(1, 1, 0.98f, 0.75f), new Color(1, 0.96f, 0.75f, 0.75f)), -12, world);
                puff.transform.position = new Vector3(cx + (k - 1.5f) * 9, cy + (k % 2) * 3, 0);
            }
        }
        // 藍黃雙色弧
        Color[] rainbow = { Pix.C(52, 170, 160), Pix.C(96, 210, 196), Pix.C(186, 236, 220), Pix.C(255, 246, 170), Pix.C(255, 226, 100), Pix.C(236, 196, 110) };
        for (int r = 0; r < rainbow.Length; r++)
            for (int a2 = 0; a2 <= 60; a2++)
            {
                float ang = Mathf.PI * a2 / 60f, rad = 70 - r * 3;
                var d = Pix.Make("Rainbow", Pix.Dot, -15, world);
                d.color = new Color(rainbow[r].r, rainbow[r].g, rainbow[r].b, 0.55f);
                d.transform.position = new Vector3(Mathf.Round(W / 2 + Mathf.Cos(ang) * rad), Mathf.Round(Floor + 40 + Mathf.Sin(ang) * rad * 0.8f), 0);
                d.transform.localScale = new Vector3(3, 3, 1);
            }
        // 地面：藍綠糖霜草地
        var ground = Pix.Make("Ground", Pix.Dot, -5, world);
        ground.color = Pix.C(96, 210, 196);
        ground.transform.position = new Vector3(W / 2, Floor / 2, 0);
        ground.transform.localScale = new Vector3(W, Floor, 1);
        var line = Pix.Make("Line", Pix.Dot, -4, world);
        line.color = Pix.C(255, 246, 170);
        line.transform.position = new Vector3(W / 2, Floor, 0);
        line.transform.localScale = new Vector3(W, 2, 1);
        foreach (var fx in new[] { 14f, 46f, 196f, 226f })
        {
            var deco = Pix.Make("Deco", Pix.Load(fx < 100 ? "snack_lollipop" : "snack_cake", new Vector2(0.5f, 0f)), -3, world);
            deco.transform.position = new Vector3(fx, 3, 0);
        }
        her = Character.Create(Boot.Outfit, world);
        ResetGame();
    }

    void ResetGame()
    {
        foreach (var o in objs) DestroyObj(o);
        objs.Clear();
        x = W / 2; vx = 0; t = 0; spawnT = 0.6f; score = 0; hurt = 0; saved = false;
    }

    void DestroyObj(Obj o)
    {
        if (o.sr) Destroy(o.sr.gameObject);
    }

    float Level => Mathf.Min(1f, t / 90f);

    void Update()
    {
        if (GameInput.Escape)
        {
            SaveResult();
            Application.Quit();
            return;
        }
        float dt = Mathf.Min(Time.deltaTime, 1f / 20f);
        her.Squash = Mathf.Max(0, her.Squash - dt * 4);
        hurt = Mathf.Max(0, hurt - dt);
        UpdateFx(dt);
        Step(dt);
        Draw();
    }

    void OnApplicationQuit() => SaveResult();

    void SaveResult()
    {
        if (saved) return;
        saved = true;
        best = Mathf.Max(best, score);
        PlayerPrefs.SetInt("best_stars", best);
        PlayerPrefs.Save();
        if (score > 0) GameResult.Add("stars", score, score, false);
    }

    void Step(float dt)
    {
        GameInput.ConsumeClick();
        t += dt;
        int dx = GameInput.Dx;
        if (dx != 0) vx = dx * Speed;
        else if (GameInput.MouseX.HasValue) vx = Mathf.Clamp((GameInput.MouseX.Value - x) * 6, -Speed, Speed);
        else vx *= 0.8f;
        her.Face = Mathf.Abs(vx) > 14 ? (vx > 0 ? 1 : -1) : 0;
        x = Mathf.Clamp(x + vx * dt, 16, W - 16);
        spawnT -= dt;
        if (spawnT <= 0)
        {
            spawnT = Random.Range(0.9f, 1.3f) * (1 - 0.6f * Level);
            // 只掉點心，沒有星星、沒有雨雲
            string kind = Snacks[Random.Range(0, Snacks.Length)];
            float sp = Random.Range(75f, 100f) + 120 * Level;
            var o = new Obj
            {
                x = Random.Range(12f, W - 12), y = H + 8, vy = sp, kind = kind,
                vx = 0, ph = Random.Range(0f, 6f)
            };
            o.sr = Pix.Make(kind, Pix.Load("snack_" + kind, new Vector2(0.5f, 0.5f)), 1, world);
            o.sr.transform.localScale = new Vector3(2, 2, 1);
            objs.Add(o);
        }
        float top = Floor + BodyH;
        objs.RemoveAll(o =>
        {
            o.y -= o.vy * dt;
            o.x = Mathf.Clamp(o.x + o.vx * dt, 6, W - 6);
            if (o.y <= top && o.y >= Floor && Mathf.Abs(o.x - x) < Catch)
            {
                score += 1;
                her.Squash = 1;
                Burst(o.x, o.y, Pix.C(255, 246, 170));
                DestroyObj(o);
                return true;
            }
            if (o.y < Floor - 4)
            {
                // 漏接：不扣生命，只消失
                DestroyObj(o);
                return true;
            }
            return false;
        });
    }

    void Burst(float bx, float by, Color c)
    {
        for (int i = 0; i < 6; i++)
        {
            float a = Random.Range(0f, Mathf.PI * 2);
            var sr = Pix.Make("Fx", Pix.Dot, 3, world);
            sr.color = c;
            fxs.Add(new Fx { x = bx, y = by, vx = Mathf.Cos(a) * 35, vy = Mathf.Sin(a) * 35 + 20, life = 0.5f, sr = sr });
        }
    }

    void UpdateFx(float dt)
    {
        fxs.RemoveAll(f =>
        {
            f.life -= dt;
            f.x += f.vx * dt;
            f.y += f.vy * dt;
            f.vy -= 60 * dt;
            f.sr.transform.position = new Vector3(Mathf.Round(f.x), Mathf.Round(f.y), 0);
            if (f.life > 0) return false;
            Destroy(f.sr.gameObject);
            return true;
        });
    }

    void Draw()
    {
        foreach (var o in objs)
            o.sr.transform.position = new Vector3(Mathf.Round(o.x), Mathf.Round(o.y), 0);
        her.Hidden = hurt > 0 && ((int)(hurt * 12)) % 2 == 1;
        her.transform.position = new Vector3(Mathf.Round(x), Floor, 0);
    }

    void OnGUI()
    {
        float z = Screen.height / H;
        int fs = Mathf.RoundToInt(11 * z);
        var uiFill = Pix.C(255, 249, 224);
        var uiLine = Pix.C(58, 168, 154);
        var uiText = Pix.C(31, 95, 90);
        var uiHi = Pix.C(201, 160, 20);
        Pix.Box(new Rect(2 * z, 2 * z, 80 * z, 30 * z), uiFill, uiLine);
        GUI.Label(new Rect(5 * z, 3 * z, 200, 40), "點心 " + score, Pix.Label(fs, uiText));
        GUI.Label(new Rect(5 * z, 16 * z, 200, 40), "最佳 " + best, Pix.Label(fs, uiText));
        GUI.Label(new Rect(6 * z, (H - 14) * z, 400, 40), "← → 移動・Esc 離開", Pix.Label(Mathf.RoundToInt(9 * z), uiHi));
    }
}
