<#
PROTOTYPE ONLY: interactive visual lab for the JARVIS overlay.

Run the comparison lab from the repository root:
  powershell -ExecutionPolicy Bypass -File jarvis\overlay\prototype_jarvis_overlay.ps1

Run the real desktop overlay demo (it closes when its controller closes):
  powershell -ExecutionPolicy Bypass -File jarvis\overlay\prototype_jarvis_overlay.ps1 -Live

Controls: 1-5 or Left/Right changes visual direction. A/S/D/F changes the
lifecycle state (armed/heard/working/speaking). Escape closes the lab.
This is a throwaway design aid: it does not change the production overlay.
#>

param(
    [switch]$Verify,
    [switch]$Live,
    [ValidateRange(0, 3600)]
    [int]$DurationSeconds = 0
)

Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

Add-Type -TypeDefinition @'
using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Text;
using System.Runtime.InteropServices;
using System.Windows.Forms;

public sealed class LabScenario
{
    public string Title, Detail, Key;
    public Color Accent;
    public LabScenario(string key, string title, string detail, Color accent)
    { Key = key; Title = title; Detail = detail; Accent = accent; }
}

public sealed class LabVariant
{
    public string Name, Personality;
    public LabVariant(string name, string personality)
    { Name = name; Personality = personality; }
}

public sealed class OverlayLab : Form
{
    const float W = 1280, H = 720;
    readonly LabScenario[] states = {
        new LabScenario("armed", "LISTENING", "Voice link live", Color.FromArgb(239, 242, 246)),
        new LabScenario("heard", "HEARD", "open the latest invoice", Color.FromArgb(203, 210, 220)),
        new LabScenario("working", "THINKING", "Finding the latest invoice...", Color.FromArgb(167, 176, 188)),
        new LabScenario("speaking", "JARVIS", "I found April's invoice in Downloads.", Color.FromArgb(246, 247, 249))
    };
    readonly LabVariant[] variants = {
        new LabVariant("Ribbon", "Quiet, elegant voice caption; the safest evolution."),
        new LabVariant("Orbit", "A cinematic AI core that feels alive without feeling loud."),
        new LabVariant("Monolith", "A confident command totem: architectural, focused, premium."),
        new LabVariant("Prism", "A sculptural assistant presence with a soft, magical center."),
        new LabVariant("Horizon", "A wide mission-control strip for a visibly capable desktop agent.")
    };
    int selectedVariant = 0;
    int selectedState = 3;

    public OverlayLab()
    {
        Text = "JARVIS Overlay Lab - PROTOTYPE";
        ClientSize = new Size(1280, 720);
        MinimumSize = new Size(980, 600);
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = Color.FromArgb(9, 16, 29);
        KeyPreview = true;
        DoubleBuffered = true;
        ResizeRedraw = true;
    }

    protected override void OnKeyDown(KeyEventArgs e)
    {
        if (e.KeyCode == Keys.Escape) { Close(); return; }
        if (e.KeyCode == Keys.Left) selectedVariant = (selectedVariant + variants.Length - 1) % variants.Length;
        if (e.KeyCode == Keys.Right) selectedVariant = (selectedVariant + 1) % variants.Length;
        if (e.KeyCode >= Keys.D1 && e.KeyCode <= Keys.D5) selectedVariant = (int)e.KeyCode - (int)Keys.D1;
        if (e.KeyCode == Keys.A) selectedState = 0;
        if (e.KeyCode == Keys.S) selectedState = 1;
        if (e.KeyCode == Keys.D) selectedState = 2;
        if (e.KeyCode == Keys.F) selectedState = 3;
        Invalidate();
        base.OnKeyDown(e);
    }

    protected override void OnPaint(PaintEventArgs eventArgs)
    {
        Graphics g = eventArgs.Graphics;
        g.SmoothingMode = SmoothingMode.AntiAlias;
        g.InterpolationMode = InterpolationMode.HighQualityBicubic;
        g.TextRenderingHint = TextRenderingHint.AntiAliasGridFit;
        float scale = Math.Min(ClientSize.Width / W, ClientSize.Height / H);
        g.TranslateTransform((ClientSize.Width - W * scale) / 2f, (ClientSize.Height - H * scale) / 2f);
        g.ScaleTransform(scale, scale);
        Desktop(g);
        Header(g);
        LabScenario state = states[selectedState];
        if (selectedVariant == 0) Ribbon(g, state);
        else if (selectedVariant == 1) Orbit(g, state);
        else if (selectedVariant == 2) Monolith(g, state);
        else if (selectedVariant == 3) Prism(g, state);
        else Horizon(g, state);
        Selector(g);
    }

    static Font MakeFont(float size, FontStyle style) { return new Font("Segoe UI", size, style, GraphicsUnit.Pixel); }
    static Color A(Color color, int alpha) { return Color.FromArgb(alpha, color); }
    static Color Hex(string value, int alpha) { return Color.FromArgb(alpha, Convert.ToInt32(value.Substring(1, 2), 16), Convert.ToInt32(value.Substring(3, 2), 16), Convert.ToInt32(value.Substring(5, 2), 16)); }

    static GraphicsPath Round(float x, float y, float w, float h, float r)
    {
        GraphicsPath path = new GraphicsPath();
        path.AddArc(x, y, r * 2, r * 2, 180, 90); path.AddArc(x + w - r * 2, y, r * 2, r * 2, 270, 90);
        path.AddArc(x + w - r * 2, y + h - r * 2, r * 2, r * 2, 0, 90); path.AddArc(x, y + h - r * 2, r * 2, r * 2, 90, 90);
        path.CloseFigure(); return path;
    }
    static void FillRound(Graphics g, float x, float y, float w, float h, float r, Brush brush) { using (GraphicsPath p = Round(x, y, w, h, r)) g.FillPath(brush, p); }
    static void StrokeRound(Graphics g, float x, float y, float w, float h, float r, Pen pen) { using (GraphicsPath p = Round(x, y, w, h, r)) g.DrawPath(pen, p); }
    static void Shadow(Graphics g, float x, float y, float w, float h, float r, int alpha)
    {
        for (int i = 8; i > 0; i--) using (SolidBrush b = new SolidBrush(Color.FromArgb(Math.Max(3, alpha / (i + 2)), 0, 0, 0))) FillRound(g, x, y + i * 1.5f, w, h, r, b);
    }
    static void DrawText(Graphics g, string value, float x, float y, float w, float h, float size, Color color, FontStyle style, StringAlignment align)
    {
        using (Font f = MakeFont(size, style)) using (SolidBrush b = new SolidBrush(color)) using (StringFormat format = new StringFormat())
        { format.Alignment = align; format.LineAlignment = StringAlignment.Center; format.Trimming = StringTrimming.EllipsisCharacter; g.DrawString(value, f, b, new RectangleF(x, y, w, h), format); }
    }
    static float Phase(LabScenario state) { return state.Key == "heard" ? 1.2f : state.Key == "working" ? 2.7f : state.Key == "speaking" ? 4.2f : 0f; }
    static void Wave(Graphics g, float x, float y, float w, float h, LabScenario state, int bars, bool quiet)
    {
        float gap = w / bars;
        for (int i = 0; i < bars; i++)
        {
            float pulse = Math.Abs((float)Math.Sin(i * .72f + Phase(state)));
            float height = 3 + pulse * (quiet ? h * .42f : h - 4), width = Math.Max(2, gap * .54f);
            using (SolidBrush b = new SolidBrush(A(state.Accent, 235 - (i % 4) * 20))) FillRound(g, x + i * gap + gap * .23f, y + h / 2 - height / 2, width, height, width / 2, b);
        }
    }

    void Desktop(Graphics g)
    {
        using (LinearGradientBrush b = new LinearGradientBrush(new Rectangle(0, 0, (int)W, (int)H), Hex("#101726", 255), Hex("#0D1320", 255), 35f)) g.FillRectangle(b, 0, 0, W, H);
        using (SolidBrush b = new SolidBrush(Hex("#18233A", 115))) g.FillRectangle(b, 0, 150, W, 410);
        for (int i = 11; i >= 1; i--)
        {
            using (SolidBrush one = new SolidBrush(Hex("#244B7A", i * 2))) g.FillEllipse(one, 240 - i * 23, 175 - i * 23, i * 46, i * 46);
            using (SolidBrush two = new SolidBrush(Hex("#6A4075", i * 2))) g.FillEllipse(two, 1080 - i * 26, 500 - i * 26, i * 52, i * 52);
        }
        using (SolidBrush b = new SolidBrush(Hex("#172238", 154))) FillRound(g, 160, 105, 960, 465, 18, b);
        using (Pen p = new Pen(Hex("#B9D6FF", 28), 1)) StrokeRound(g, 160, 105, 960, 465, 18, p);
        using (SolidBrush b = new SolidBrush(Hex("#0E1626", 145))) g.FillRectangle(b, 160, 105, 960, 48);
        using (SolidBrush b = new SolidBrush(Hex("#B8D5FF", 80))) { g.FillEllipse(b, 184, 125, 8, 8); g.FillEllipse(b, 201, 125, 8, 8); g.FillEllipse(b, 218, 125, 8, 8); }
        DrawText(g, "WORKSPACE / CONTEXT", 250, 114, 400, 28, 10, Hex("#C8D8F2", 105), FontStyle.Bold, StringAlignment.Near);
        int[] widths = { 445, 560, 375, 500, 280 }; using (SolidBrush b = new SolidBrush(Hex("#D7E5FF", 20))) for (int i = 0; i < widths.Length; i++) FillRound(g, 210, 190 + i * 48, widths[i], 11, 5, b);
        using (SolidBrush b = new SolidBrush(Hex("#72C8FF", 36))) FillRound(g, 785, 190, 270, 220, 14, b);
        using (SolidBrush b = new SolidBrush(Hex("#9CBFFF", 34))) { FillRound(g, 810, 218, 220, 18, 6, b); foreach (int yy in new[] { 260, 290, 320, 350 }) FillRound(g, 810, yy, 180, 10, 5, b); }
        using (SolidBrush b = new SolidBrush(Hex("#07101C", 190))) g.FillRectangle(b, 0, 674, W, 46);
        for (int i = 0; i < 7; i++) using (SolidBrush b = new SolidBrush(Hex("#C7D9F8", i == 3 ? 115 : 48))) FillRound(g, 510 + i * 38, 686, 22, 22, 6, b);
    }

    void Header(Graphics g)
    {
        using (SolidBrush b = new SolidBrush(Color.FromArgb(180, 7, 12, 23))) FillRound(g, 26, 22, 510, 59, 14, b);
        using (Pen p = new Pen(Hex("#E4EDFF", 34), 1)) StrokeRound(g, 26, 22, 510, 59, 14, p);
        DrawText(g, "JARVIS OVERLAY LAB", 46, 32, 190, 16, 10, Hex("#DCEAFF", 180), FontStyle.Bold, StringAlignment.Near);
        DrawText(g, "STYLE " + (selectedVariant + 1) + "/5  -  " + variants[selectedVariant].Name.ToUpper(), 46, 49, 320, 20, 15, Color.White, FontStyle.Bold, StringAlignment.Near);
        DrawText(g, states[selectedState].Title, 380, 38, 132, 28, 11, states[selectedState].Accent, FontStyle.Bold, StringAlignment.Far);
    }

    void Ribbon(Graphics g, LabScenario s)
    {
        const float x = 318, y = 582, w = 644, h = 68; Shadow(g, x, y, w, h, 34, 105);
        using (GraphicsPath p = Round(x, y, w, h, 34)) using (LinearGradientBrush b = new LinearGradientBrush(new PointF(x, y), new PointF(x + w, y + h), Hex("#171E2E", 244), Hex("#0A0F1B", 248))) using (Pen rim = new Pen(Hex("#E4EDFF", 45), 1)) { g.FillPath(b, p); g.DrawPath(rim, p); }
        using (LinearGradientBrush glow = new LinearGradientBrush(new PointF(x + 26, 0), new PointF(x + 215, 0), Color.Transparent, Color.Transparent)) using (Pen p = new Pen(glow, 2.3f))
        { glow.InterpolationColors = new ColorBlend { Colors = new[] { A(s.Accent, 0), A(s.Accent, 190), A(s.Accent, 0) }, Positions = new[] { 0f, .45f, 1f } }; p.StartCap = LineCap.Round; p.EndCap = LineCap.Round; g.DrawLine(p, x + 26, y + h - 2, x + 215, y + h - 2); }
        using (SolidBrush b = new SolidBrush(s.Accent)) g.FillEllipse(b, 348, 609, 14, 14);
        DrawText(g, s.Title, 375, 593, 120, 17, 10, Color.White, FontStyle.Bold, StringAlignment.Near); DrawText(g, s.Detail, 375, 611, 290, 22, 13, Hex("#D5DEEF", 220), FontStyle.Regular, StringAlignment.Near); Wave(g, 744, 595, 172, 42, s, 17, s.Key == "heard");
    }

    void Orbit(Graphics g, LabScenario s)
    {
        const float x = 1014, y = 510;
        for (int i = 8; i > 0; i--) using (SolidBrush b = new SolidBrush(Color.FromArgb(120 / (i + 2), 0, 0, 0))) g.FillEllipse(b, x - 112, y - 112 + i * 1.5f, 224, 224);
        using (SolidBrush b = new SolidBrush(Hex("#0A1020", 238))) g.FillEllipse(b, x - 112, y - 112, 224, 224); using (Pen p = new Pen(Hex("#CFE2FF", 42), 1)) g.DrawEllipse(p, x - 112, y - 112, 224, 224);
        using (SolidBrush b = new SolidBrush(Hex("#111B30", 230))) g.FillEllipse(b, x - 75, y - 75, 150, 150); using (Pen p = new Pen(A(s.Accent, 105), 1.5f)) g.DrawEllipse(p, x - 75, y - 75, 150, 150);
        for (int i = 0; i < 20; i++) { if (i == 3 || i == 4 || i == 5) continue; float a = (i * 18 + Phase(s) * 9) * (float)Math.PI / 180f, inn = i % 2 == 1 ? 88 : 84, outt = i % 2 == 1 ? 102 : 108; using (Pen p = new Pen(A(s.Accent, i % 2 == 1 ? 110 : 165), 1.4f)) { p.StartCap = p.EndCap = LineCap.Round; g.DrawLine(p, x + (float)Math.Cos(a) * inn, y + (float)Math.Sin(a) * inn, x + (float)Math.Cos(a) * outt, y + (float)Math.Sin(a) * outt); } }
        using (SolidBrush b = new SolidBrush(A(s.Accent, 36))) g.FillEllipse(b, x - 54, y - 54, 108, 108); using (SolidBrush b = new SolidBrush(Hex("#0B1020", 220))) g.FillEllipse(b, x - 42, y - 42, 84, 84); using (Pen p = new Pen(A(s.Accent, 170), 1.4f)) g.DrawEllipse(p, x - 42, y - 42, 84, 84);
        Wave(g, x - 34, y - 21, 68, 42, s, 9, s.Key == "heard"); DrawText(g, s.Title, 912, 622, 204, 16, 10, s.Accent, FontStyle.Bold, StringAlignment.Center); DrawText(g, s.Detail, 866, 643, 296, 20, 11, Hex("#E2EBFA", 210), FontStyle.Regular, StringAlignment.Center);
    }

    void Monolith(Graphics g, LabScenario s)
    {
        PointF[] q = { new PointF(82, 274), new PointF(332, 274), new PointF(332, 578), new PointF(302, 608), new PointF(52, 608), new PointF(52, 304) };
        for (int i = 8; i > 0; i--) using (SolidBrush b = new SolidBrush(Color.FromArgb(120 / (i + 2), 0, 0, 0))) g.FillPolygon(b, OffsetPoints(q, 0, i * 1.5f));
        using (GraphicsPath p = new GraphicsPath()) using (LinearGradientBrush b = new LinearGradientBrush(new PointF(52, 274), new PointF(332, 608), Hex("#101827", 247), Hex("#050911", 248))) using (Pen rim = new Pen(A(s.Accent, 105), 1)) { p.AddPolygon(q); g.FillPath(b, p); g.DrawPath(rim, p); }
        using (Pen p = new Pen(s.Accent, 3.2f)) g.DrawLine(p, 52, 309, 52, 566); DrawText(g, "JARVIS", 84, 310, 170, 18, 11, Color.White, FontStyle.Bold, StringAlignment.Near); DrawText(g, s.Title, 84, 342, 200, 52, 27, s.Accent, FontStyle.Bold, StringAlignment.Near);
        using (SolidBrush b = new SolidBrush(Hex("#E1EBFE", 25))) FillRound(g, 84, 414, 208, 2, 1, b); DrawText(g, s.Detail, 84, 432, 190, 60, 13, Hex("#D6E0F2", 220), FontStyle.Regular, StringAlignment.Near); Wave(g, 82, 528, 200, 36, s, 22, s.Key == "heard"); DrawText(g, "VOICE INTERFACE", 84, 573, 160, 15, 8, Hex("#B6C8E6", 120), FontStyle.Bold, StringAlignment.Near);
    }

    static PointF[] OffsetPoints(PointF[] source, float dx, float dy) { PointF[] result = new PointF[source.Length]; for (int i = 0; i < source.Length; i++) result[i] = new PointF(source[i].X + dx, source[i].Y + dy); return result; }

    void Prism(Graphics g, LabScenario s)
    {
        const float x = 642, y = 366; PointF[] diamond = { new PointF(x, y - 138), new PointF(x + 138, y), new PointF(x, y + 138), new PointF(x - 138, y) };
        for (int i = 8; i > 0; i--) using (SolidBrush b = new SolidBrush(Color.FromArgb(100 / (i + 2), 0, 0, 0))) g.FillPolygon(b, OffsetPoints(diamond, 0, i * 1.5f));
        using (GraphicsPath p = new GraphicsPath()) using (LinearGradientBrush b = new LinearGradientBrush(new PointF(535, 258), new PointF(747, 474), Hex("#1D2541", 238), Hex("#0A0F20", 246))) using (Pen rim = new Pen(Hex("#E9EEFF", 48), 1)) { p.AddPolygon(diamond); g.FillPath(b, p); g.DrawPath(rim, p); }
        foreach (PointF point in diamond) using (Pen p = new Pen(A(s.Accent, 66), 1)) g.DrawLine(p, x, y, point.X, point.Y);
        using (SolidBrush b = new SolidBrush(A(s.Accent, 42))) g.FillEllipse(b, x - 61, y - 61, 122, 122); using (SolidBrush b = new SolidBrush(Hex("#0B1020", 220))) g.FillEllipse(b, x - 42, y - 42, 84, 84); using (Pen p = new Pen(A(s.Accent, 170), 1.4f)) g.DrawEllipse(p, x - 42, y - 42, 84, 84);
        Wave(g, x - 25, y - 18, 50, 36, s, 7, s.Key == "heard"); DrawText(g, s.Title, 502, 505, 280, 20, 11, s.Accent, FontStyle.Bold, StringAlignment.Center); DrawText(g, s.Detail, 490, 528, 304, 20, 13, Hex("#E2E8F7", 225), FontStyle.Regular, StringAlignment.Center);
    }

    void Horizon(Graphics g, LabScenario s)
    {
        const float x = 150, y = 555, w = 980, h = 82; Shadow(g, x, y, w, h, 14, 128);
        using (GraphicsPath p = Round(x, y, w, h, 14)) using (LinearGradientBrush b = new LinearGradientBrush(new PointF(x, y), new PointF(x + w, y + h), Hex("#081522", 246), Hex("#0A0B15", 250))) using (Pen rim = new Pen(Hex("#CFDDFF", 38), 1)) { g.FillPath(b, p); g.DrawPath(rim, p); }
        using (SolidBrush b = new SolidBrush(s.Accent)) g.FillEllipse(b, 182, 590, 12, 12); DrawText(g, s.Title, 208, 568, 188, 18, 10, s.Accent, FontStyle.Bold, StringAlignment.Near); DrawText(g, s.Detail, 208, 588, 330, 24, 14, Hex("#EEF4FF", 235), FontStyle.Regular, StringAlignment.Near);
        using (Pen p = new Pen(Hex("#E1ECFF", 20), 1)) g.DrawLine(p, 566, 570, 566, 622); Wave(g, 598, 570, 328, 48, s, 37, s.Key == "heard"); DrawText(g, "SYSTEM ONLINE", 950, 578, 146, 16, 9, Hex("#C9D6ED", 132), FontStyle.Bold, StringAlignment.Far); DrawText(g, "VOICE / LOCAL", 950, 597, 146, 14, 9, Hex("#C9D6ED", 92), FontStyle.Regular, StringAlignment.Far);
    }

    void Selector(Graphics g)
    {
        using (SolidBrush b = new SolidBrush(Color.FromArgb(206, 8, 14, 25))) FillRound(g, 319, 655, 642, 44, 20, b);
        for (int i = 0; i < variants.Length; i++)
        {
            int x = 340 + i * 124; bool active = i == selectedVariant;
            using (SolidBrush b = new SolidBrush(active ? A(states[selectedState].Accent, 40) : Hex("#E4EDFF", 10))) FillRound(g, x, 663, 112, 28, 12, b);
            DrawText(g, (i + 1) + "  " + variants[i].Name.ToUpper(), x, 663, 112, 28, 9, active ? Color.White : Hex("#DCEAFF", 125), active ? FontStyle.Bold : FontStyle.Regular, StringAlignment.Center);
        }
        DrawText(g, "1-5 / arrows: style    A: armed    S: heard    D: working    F: speaking    Esc: close", 30, 642, 1220, 15, 9, Hex("#DCEAFF", 128), FontStyle.Regular, StringAlignment.Center);
        DrawText(g, variants[selectedVariant].Personality, 30, 84, 1220, 16, 10, Hex("#DCEAFF", 144), FontStyle.Regular, StringAlignment.Center);
    }
}

public sealed class MonolithLiveOverlay : Form
{
    const int WidthPx = 296, HeightPx = 338;
    const int WS_EX_LAYERED = 0x00080000, WS_EX_TRANSPARENT = 0x00000020, WS_EX_NOACTIVATE = 0x08000000, WS_EX_TOOLWINDOW = 0x00000080;
    const int ULW_ALPHA = 0x00000002, AC_SRC_OVER = 0x00, AC_SRC_ALPHA = 0x01;
    readonly LabScenario[] states = {
        new LabScenario("armed", "LISTENING", "Voice link live", Color.FromArgb(232, 236, 241)),
        new LabScenario("heard", "HEARD", "open the latest invoice", Color.FromArgb(214, 220, 228)),
        new LabScenario("working", "THINKING", "Finding the latest invoice...", Color.FromArgb(190, 197, 206)),
        new LabScenario("speaking", "SPEAKING", "I found April's invoice in Downloads.", Color.FromArgb(242, 244, 247))
    };
    readonly Timer timer = new Timer();
    readonly int durationTicks;
    int ticks;
    int sourceState;
    int targetState;
    int transitionStartedAt;

    [StructLayout(LayoutKind.Sequential, Pack = 1)]
    struct BlendFunction { public byte BlendOp, BlendFlags, SourceConstantAlpha, AlphaFormat; }
    [DllImport("user32.dll", SetLastError = true)]
    static extern bool UpdateLayeredWindow(IntPtr hwnd, IntPtr hdcDst, ref Point destination, ref Size size, IntPtr hdcSrc, ref Point source, int colorKey, ref BlendFunction blend, int flags);
    [DllImport("user32.dll")] static extern IntPtr GetDC(IntPtr hwnd);
    [DllImport("user32.dll")] static extern int ReleaseDC(IntPtr hwnd, IntPtr hdc);
    [DllImport("gdi32.dll")] static extern IntPtr CreateCompatibleDC(IntPtr hdc);
    [DllImport("gdi32.dll")] static extern bool DeleteDC(IntPtr hdc);
    [DllImport("gdi32.dll")] static extern IntPtr SelectObject(IntPtr hdc, IntPtr obj);
    [DllImport("gdi32.dll")] static extern bool DeleteObject(IntPtr obj);

    public MonolithLiveOverlay(int durationSeconds)
    {
        durationTicks = durationSeconds * 60;
        FormBorderStyle = FormBorderStyle.None;
        StartPosition = FormStartPosition.Manual;
        TopMost = true;
        ShowInTaskbar = false;
        Size = new Size(WidthPx, HeightPx);
        Rectangle screen = Screen.PrimaryScreen.WorkingArea;
        Location = new Point(screen.Left + 34, screen.Bottom - HeightPx - 42);
        timer.Interval = 16;
        timer.Tick += new EventHandler(OnTick);
        timer.Start();
    }

    protected override CreateParams CreateParams
    {
        get
        {
            CreateParams result = base.CreateParams;
            result.ExStyle |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW;
            return result;
        }
    }

    protected override void OnShown(EventArgs args) { base.OnShown(args); PresentFrame(); }
    protected override void OnPaint(PaintEventArgs args) { }
    protected override void OnPaintBackground(PaintEventArgs args) { }

    void OnTick(object sender, EventArgs args)
    {
        ticks++;
        if (durationTicks > 0 && ticks >= durationTicks) { Close(); return; }
        PresentFrame();
    }
    protected override void OnFormClosed(FormClosedEventArgs args) { timer.Stop(); timer.Dispose(); base.OnFormClosed(args); }

    public string TargetTitle { get { return states[targetState].Title; } }
    public void SetState(int stateIndex)
    {
        if (stateIndex < 0 || stateIndex >= states.Length || stateIndex == targetState) return;
        float currentTransition = Math.Min(1f, (ticks - transitionStartedAt) / 48f);
        if (currentTransition >= .5f) sourceState = targetState;
        targetState = stateIndex;
        transitionStartedAt = ticks;
        PresentFrame();
    }

    void PresentFrame()
    {
        if (!IsHandleCreated) return;
        float transitionRaw = Math.Min(1f, (ticks - transitionStartedAt) / 48f);
        float transition = sourceState == targetState ? 0f : SmoothStep(transitionRaw);
        LabScenario current = states[sourceState];
        LabScenario next = states[targetState];
        if (transitionRaw >= 1f) { sourceState = targetState; current = states[targetState]; transition = 0f; }
        using (Bitmap frame = RenderFrame(current, next, transition, ticks * .035f))
        {
            IntPtr desktop = GetDC(IntPtr.Zero);
            IntPtr memory = CreateCompatibleDC(desktop);
            IntPtr hBitmap = frame.GetHbitmap(Color.FromArgb(0));
            IntPtr previous = SelectObject(memory, hBitmap);
            Point destination = Location, source = new Point(0, 0);
            Size size = frame.Size;
            BlendFunction blend = new BlendFunction { BlendOp = AC_SRC_OVER, BlendFlags = 0, SourceConstantAlpha = 255, AlphaFormat = AC_SRC_ALPHA };
            UpdateLayeredWindow(Handle, desktop, ref destination, ref size, memory, ref source, 0, ref blend, ULW_ALPHA);
            SelectObject(memory, previous);
            DeleteObject(hBitmap);
            DeleteDC(memory);
            ReleaseDC(IntPtr.Zero, desktop);
        }
    }

    public static void VerifyFrame()
    {
        LabScenario state = new LabScenario("armed", "LISTENING", "Voice link live", Color.FromArgb(232, 236, 241));
        using (Bitmap frame = RenderFrame(state, state, 0f, 0f))
        {
            if (frame.GetPixel(0, 0).A != 0) throw new InvalidOperationException("Frame corner is not transparent.");
            bool softEdge = false;
            for (int y = 0; y < frame.Height && !softEdge; y++) for (int x = 0; x < frame.Width; x++)
            {
                Color pixel = frame.GetPixel(x, y);
                if (pixel.A > 0 && pixel.A < 255)
                {
                    if (pixel.R > 200 && pixel.B > 200 && pixel.G < 80) throw new InvalidOperationException("Magenta key-colour fringe detected.");
                    softEdge = true;
                }
            }
            if (!softEdge) throw new InvalidOperationException("No anti-aliased alpha edge was rendered.");
        }
    }

    static Bitmap RenderFrame(LabScenario current, LabScenario next, float transition, float livePhase)
    {
        Bitmap frame = new Bitmap(WidthPx, HeightPx, System.Drawing.Imaging.PixelFormat.Format32bppPArgb);
        using (Graphics g = Graphics.FromImage(frame))
        {
            g.Clear(Color.Transparent);
            g.CompositingQuality = CompositingQuality.HighQuality;
            g.SmoothingMode = SmoothingMode.HighQuality;
            g.InterpolationMode = InterpolationMode.HighQualityBicubic;
            g.PixelOffsetMode = PixelOffsetMode.HighQuality;
            g.TextRenderingHint = TextRenderingHint.AntiAliasGridFit;
            DrawMonolith(g, current, next, transition, livePhase);
        }
        return frame;
    }

    static GraphicsPath RoundRect(float x, float y, float w, float h, float r)
    {
        GraphicsPath path = new GraphicsPath();
        path.AddArc(x, y, r * 2, r * 2, 180, 90); path.AddArc(x + w - r * 2, y, r * 2, r * 2, 270, 90);
        path.AddArc(x + w - r * 2, y + h - r * 2, r * 2, r * 2, 0, 90); path.AddArc(x, y + h - r * 2, r * 2, r * 2, 90, 90);
        path.CloseFigure(); return path;
    }
    static GraphicsPath MonolithPath(float x, float y, float w, float h, float cut)
    {
        GraphicsPath path = new GraphicsPath();
        path.AddPolygon(new[] {
            new PointF(x + cut, y), new PointF(x + w, y),
            new PointF(x + w, y + h - cut), new PointF(x + w - cut, y + h),
            new PointF(x, y + h), new PointF(x, y + cut)
        });
        return path;
    }
    static Font MakeFont(float size, FontStyle style) { return new Font("Segoe UI", size, style, GraphicsUnit.Pixel); }
    static Color Alpha(Color color, int value) { return Color.FromArgb(value, color); }
    static Color Fade(Color color, float opacity) { return Color.FromArgb(Math.Max(0, Math.Min(255, (int)(color.A * opacity))), color.R, color.G, color.B); }
    static float SmoothStep(float t) { t = Math.Max(0f, Math.Min(1f, t)); return t * t * (3f - 2f * t); }
    static void Label(Graphics g, string value, float x, float y, float w, float h, float size, Color color, FontStyle style)
    {
        using (Font font = MakeFont(size, style)) using (SolidBrush brush = new SolidBrush(color)) using (StringFormat format = new StringFormat())
        { format.Alignment = StringAlignment.Near; format.LineAlignment = StringAlignment.Center; format.Trimming = StringTrimming.EllipsisCharacter; g.DrawString(value, font, brush, new RectangleF(x, y, w, h), format); }
    }
    static void RoundedFill(Graphics g, float x, float y, float w, float h, float r, Brush brush) { using (GraphicsPath path = RoundRect(x, y, w, h, r)) g.FillPath(brush, path); }
    static float StatePhase(LabScenario state) { return state.Key == "heard" ? .8f : state.Key == "working" ? 1.8f : state.Key == "speaking" ? 3.2f : 0f; }
    static void Wave(Graphics g, LabScenario state, float livePhase, float opacity)
    {
        if (opacity <= 0f) return;
        const int count = 24;
        for (int i = 0; i < count; i++)
        {
            float pulse = Math.Abs((float)Math.Sin(i * .66f + StatePhase(state) + livePhase));
            float height = 3 + pulse * (state.Key == "heard" ? 10 : 22), width = 3.6f, x = 49 + i * 8.0f;
            int alpha = (int)((156 + (i % 3) * 18) * opacity);
            using (SolidBrush brush = new SolidBrush(Color.FromArgb(alpha, 230, 234, 239))) RoundedFill(g, x, 248 - height / 2, width, height, width / 2, brush);
        }
    }
    static void RailFlow(Graphics g, float livePhase)
    {
        for (int i = 0; i < 3; i++)
        {
            float position = (livePhase * .12f + i * .34f) % 1f;
            float intensity = (float)Math.Sin(position * Math.PI);
            using (SolidBrush glow = new SolidBrush(Color.FromArgb((int)(56 * intensity), 238, 242, 246))) g.FillEllipse(glow, 40, 70 + position * 190, 6, 6);
        }
    }
    static void StateContent(Graphics g, LabScenario state, float opacity, float livePhase)
    {
        if (opacity <= 0f) return;
        Label(g, state.Title, 59, 84, 190, 35, 20, Fade(Color.FromArgb(241, 244, 247, 250), opacity), FontStyle.Bold);
        Label(g, state.Detail, 59, 158, 174, 43, 12, Fade(Color.FromArgb(181, 215, 221, 230), opacity), FontStyle.Regular);
        Wave(g, state, livePhase, opacity);
        Label(g, "VOICE  /  LOCAL", 59, 278, 165, 16, 8, Fade(Color.FromArgb(102, 201, 208, 218), opacity), FontStyle.Bold);
    }
    static void DrawMonolith(Graphics g, LabScenario current, LabScenario next, float transition, float livePhase)
    {
        const float x = 18, y = 14, w = 260, h = 308, cut = 28;
        float breathe = .5f + .5f * (float)Math.Sin(livePhase * .55f);
        for (int i = 9; i > 0; i--)
        using (SolidBrush shadow = new SolidBrush(Color.FromArgb(80 / (i + 2), 0, 0, 0)))
        using (GraphicsPath path = MonolithPath(x, y, w, h, cut))
        using (Matrix offset = new Matrix())
        {
            offset.Translate(0, i * 1.4f);
            path.Transform(offset);
            g.FillPath(shadow, path);
        }
        using (GraphicsPath shell = MonolithPath(x, y, w, h, cut))
        using (LinearGradientBrush glass = new LinearGradientBrush(new PointF(x, y), new PointF(x + w, y + h), Color.FromArgb(222, 25, 29, 35), Color.FromArgb(190, 8, 10, 14)))
        using (Pen rim = new Pen(Color.FromArgb((int)(40 + breathe * 12), 255, 255, 255), 1)) { g.FillPath(glass, shell); g.DrawPath(rim, shell); }
        using (GraphicsPath sheen = MonolithPath(x + 12, y + 12, w - 24, h - 24, 17)) using (Pen p = new Pen(Color.FromArgb((int)(10 + breathe * 10), 255, 255, 255), 1)) g.DrawPath(p, sheen);
        using (Pen rail = new Pen(Color.FromArgb(115, 237, 240, 244), 1.2f)) g.DrawLine(rail, 43, 62, 43, 276);
        RailFlow(g, livePhase);
        using (SolidBrush dot = new SolidBrush(Color.FromArgb(224, 235, 238, 242))) g.FillEllipse(dot, 59, 51, 6, 6);
        Label(g, "JARVIS", 75, 43, 150, 20, 9, Color.FromArgb(190, 224, 229, 235), FontStyle.Bold);
        using (SolidBrush line = new SolidBrush(Color.FromArgb(24, 255, 255, 255))) g.FillRectangle(line, 59, 136, 168, 1);
        StateContent(g, current, 1f - transition, livePhase);
        StateContent(g, next, transition, livePhase + .18f);
    }
}

public sealed class OverlayDemoController : Form
{
    readonly MonolithLiveOverlay overlay;
    readonly Timer flowTimer = new Timer();
    readonly Label status = new Label();
    int flowStep;

    public OverlayDemoController(int durationSeconds)
    {
        overlay = new MonolithLiveOverlay(durationSeconds);
        Text = "JARVIS Overlay Demo";
        FormBorderStyle = FormBorderStyle.FixedToolWindow;
        StartPosition = FormStartPosition.Manual;
        ClientSize = new Size(334, 248);
        BackColor = Color.FromArgb(22, 26, 32);
        ForeColor = Color.FromArgb(235, 239, 244);
        Rectangle screen = Screen.PrimaryScreen.WorkingArea;
        Location = new Point(screen.Right - Width - 36, screen.Bottom - Height - 52);

        Label heading = new Label { Text = "JARVIS / LIVE OVERLAY", ForeColor = Color.White, Font = new Font("Segoe UI", 11, FontStyle.Bold), Location = new Point(18, 17), Size = new Size(290, 24) };
        Label help = new Label { Text = "Drive the real click-through overlay state by state.", ForeColor = Color.FromArgb(177, 188, 202), Font = new Font("Segoe UI", 8.5f), Location = new Point(18, 43), Size = new Size(290, 22) };
        status.Text = "STATE  /  LISTENING";
        status.ForeColor = Color.FromArgb(210, 220, 232);
        status.Font = new Font("Segoe UI", 8, FontStyle.Bold);
        status.Location = new Point(18, 70); status.Size = new Size(294, 20);
        Controls.Add(heading); Controls.Add(help); Controls.Add(status);

        AddStateButton("Armed", 0, 18, 100); AddStateButton("Heard", 1, 174, 100);
        AddStateButton("Working", 2, 18, 136); AddStateButton("Speaking", 3, 174, 136);
        Button flow = MakeButton("Run full voice flow", 18, 184, 204, 30); flow.Click += new EventHandler(RunFlow); Controls.Add(flow);
        Button close = MakeButton("Close", 230, 184, 84, 30); close.Click += delegate { Close(); }; Controls.Add(close);

        flowTimer.Interval = 1600;
        flowTimer.Tick += new EventHandler(AdvanceFlow);
    }

    protected override void OnShown(EventArgs args) { base.OnShown(args); overlay.Show(); }
    protected override void OnFormClosed(FormClosedEventArgs args) { flowTimer.Stop(); flowTimer.Dispose(); overlay.Close(); base.OnFormClosed(args); }

    void AddStateButton(string label, int state, int x, int y)
    {
        Button button = MakeButton(label, x, y, 140, 28);
        button.Click += delegate { flowTimer.Stop(); overlay.SetState(state); status.Text = "STATE  /  " + overlay.TargetTitle; };
        Controls.Add(button);
    }
    static Button MakeButton(string text, int x, int y, int width, int height)
    {
        Button button = new Button { Text = text, FlatStyle = FlatStyle.Flat, BackColor = Color.FromArgb(35, 41, 50), ForeColor = Color.FromArgb(230, 235, 242), Font = new Font("Segoe UI", 8.5f, FontStyle.Regular), Location = new Point(x, y), Size = new Size(width, height), TabStop = false };
        button.FlatAppearance.BorderColor = Color.FromArgb(65, 74, 88); button.FlatAppearance.MouseOverBackColor = Color.FromArgb(49, 58, 70);
        return button;
    }
    void RunFlow(object sender, EventArgs args) { flowStep = 0; flowTimer.Start(); AdvanceFlow(sender, args); }
    void AdvanceFlow(object sender, EventArgs args)
    {
        if (flowStep >= 4) { flowTimer.Stop(); return; }
        overlay.SetState(flowStep++);
        status.Text = "STATE  /  " + overlay.TargetTitle;
    }
}
'@ -ReferencedAssemblies System.Drawing, System.Windows.Forms

if ($Verify) {
    [MonolithLiveOverlay]::VerifyFrame()
    Write-Output 'Overlay lab compiled successfully.'
} elseif ($Live) {
    [System.Windows.Forms.Application]::EnableVisualStyles()
    [System.Windows.Forms.Application]::Run([OverlayDemoController]::new($DurationSeconds))
} else {
    [System.Windows.Forms.Application]::EnableVisualStyles()
    [System.Windows.Forms.Application]::Run([OverlayLab]::new())
}
