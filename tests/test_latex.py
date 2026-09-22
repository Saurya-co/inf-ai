"""LaTeX math -> Unicode render helper (INF ai, readability fix)."""

import unittest

from app.core.latex import latex_to_unicode as t


class TestLatexToUnicode(unittest.TestCase):
    def test_display_math_photosynthesis(self):
        out = t(r"\[ 6CO_2 + 6H_2O \xrightarrow{Sunlight, Chlorophyll} C_6H_{12}O_6 + 6O_2 \]")
        self.assertIn("6CO₂ + 6H₂O → (Sunlight, Chlorophyll) C₆H₁₂O₆ + 6O₂", out)
        self.assertNotIn("\\", out)

    def test_inline_math_frac_sqrt(self):
        out = t(r"The roots are \(x = \frac{-b \pm \sqrt{\Delta}}{2a}\) ok")
        self.assertIn("x = -b ± √(Δ)/2a", out)

    def test_double_dollar_block(self):
        out = t("$$E = mc^2$$")
        self.assertIn("E = mc²", out)
        self.assertNotIn("$", out)

    def test_bare_chemistry_subscripts(self):
        self.assertIn("H₂O", t("Photosynthesis needs H_2O and CO_2."))
        self.assertIn("C₆H₁₂O₆", t("makes C_6H_{12}O_6 daily"))
        self.assertIn("SO₄²⁻", t("ion SO_4^{2-} here"))

    def test_currency_dollars_untouched(self):
        self.assertEqual(t("Price is $5 and $10 total"), "Price is $5 and $10 total")

    def test_math_dollar_with_markers(self):
        self.assertIn("α + β", t(r"angles $\alpha + \beta$ done"))

    def test_code_fence_verbatim(self):
        src = "```tex\nH_2O \\[x\\]\n```"
        self.assertEqual(t(src), src)

    def test_emphasis_untouched(self):
        self.assertEqual(t("This is _italic_ text"), "This is _italic_ text")

    def test_greek_and_symbols(self):
        out = t(r"\(\alpha \cdot \beta \approx \pi \times \infty\)")
        self.assertIn("α · β ≈ π × ∞", out)

    def test_idempotent(self):
        once = t(r"\[ 6CO_2 + 6H_2O \xrightarrow{sun} C_6H_{12}O_6 + 6O_2 \]")
        self.assertEqual(t(once), once)

    def test_empty_and_non_string(self):
        self.assertEqual(t(""), "")
        self.assertEqual(t(None), "")
        self.assertEqual(t("plain words, no tex here"), "plain words, no tex here")


if __name__ == "__main__":
    unittest.main()
