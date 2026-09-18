import unittest

from form_media import (
    extract_rendered_image_refs,
    is_trusted_google_form_image_url,
    split_item_image_refs,
    upgrade_google_form_image_url,
)


class RenderedImageDiscoveryTests(unittest.TestCase):
    def test_maps_question_and_choice_images_by_item_id(self):
        html = """
        <div data-item-id="123">
          <img src="https://docs.google.com/forms-images-rt/question=w320" alt="diagram">
          <div role="radio" data-value="London">
            <img src="https://docs.google.com/forms-images-rt/london=w180">
          </div>
          <div role="radio" data-value="Paris">
            <img src="https://lh3.googleusercontent.com/paris=w180">
          </div>
        </div>
        <img src="https://www.gstatic.com/logo.svg">
        """

        grouped = extract_rendered_image_refs(html)
        question, choices = split_item_image_refs(grouped["123"], ["London", "Paris"])

        self.assertEqual([ref.alt_text for ref in question], ["diagram"])
        self.assertEqual(choices[0][0].choice_value, "London")
        self.assertEqual(choices[1][0].choice_value, "Paris")

    def test_ignores_theme_images_without_item_id(self):
        html = '<img src="https://lh5.googleusercontent.com/banner=w1200">'
        self.assertEqual(extract_rendered_image_refs(html), {})

    def test_trusts_only_known_google_form_image_hosts(self):
        self.assertTrue(is_trusted_google_form_image_url(
            "https://docs.google.com/forms-images-rt/token=w320"
        ))
        self.assertTrue(is_trusted_google_form_image_url(
            "https://lh3.googleusercontent.com/token=w320"
        ))
        self.assertFalse(is_trusted_google_form_image_url(
            "https://example.com/pretend-googleusercontent.com/image.png"
        ))

    def test_upgrades_rendered_thumbnail_size(self):
        url = "https://docs.google.com/forms-images-rt/token=w155"
        self.assertEqual(
            upgrade_google_form_image_url(url),
            "https://docs.google.com/forms-images-rt/token=s1600",
        )


if __name__ == "__main__":
    unittest.main()
