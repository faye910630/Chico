using UnityEngine;

/// <summary>
/// 小遊戲裡的 Chico：和桌寵同一套 PSD 點陣化的 N×N 圖（正面／左／右），落地壓扁、會眨眼。
/// 原點在腳底中央。
/// </summary>
public class Character : MonoBehaviour
{
    SpriteRenderer body;
    Sprite front, left, right, blink;
    public int Face;            // 0 正面、1 往右、-1 往左
    public float Squash;        // 0~1，落地壓扁
    public bool Hidden;
    float blinkT = 3f;

    const float FeetPad = 1f;   // 與桌寵 full() 腳底透明邊一致

    public static Character Create(int outfit, Transform parent)
    {
        var go = new GameObject("Chico");
        go.transform.SetParent(parent, false);
        var c = go.AddComponent<Character>();
        string dir = "outfit" + outfit + "/";
        var bottom = new Vector2(0.5f, 0f);
        if (Resources.Load<Texture2D>("Pixel/" + dir + "front") == null) dir = "outfit0/";
        c.front = Pix.Load(dir + "front", bottom);
        c.left = Pix.Load(dir + "left", bottom);
        c.right = Pix.Load(dir + "right", bottom);
        c.blink = Resources.Load<Texture2D>("Pixel/" + dir + "front_blink") != null
            ? Pix.Load(dir + "front_blink", bottom) : c.front;
        c.body = Pix.Make("Body", c.front, 2, go.transform);
        return c;
    }

    void LateUpdate()
    {
        blinkT -= Time.deltaTime;
        if (blinkT < -0.13f) blinkT = Random.Range(2.2f, 5.5f);
        body.enabled = !Hidden;
        body.sprite = Face == 0 ? (blinkT < 0 ? blink : front) : (Face > 0 ? right : left);
        float sq = Squash;
        body.transform.localPosition = new Vector3(0f, -FeetPad * (1f - 0.15f * sq), 0f);
        body.transform.localScale = new Vector3(1f + 0.1f * sq, 1f - 0.15f * sq, 1f);
    }
}
