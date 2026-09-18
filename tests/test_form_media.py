import unittest

from form_media import (
    build_preview_page_payloads,
    extract_form_page_state,
    extract_rendered_image_refs,
    find_blob_image_page_indexes,
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

    def test_reads_lazy_loaded_and_srcset_images(self):
        html = """
        <div data-item-id="lazy-question">
          <img src="data:image/gif;base64,AAAA"
               data-src="https://docs.google.com/forms-images-rt/lazy=w640">
        </div>
        <img data-item-id="srcset-question"
             srcset="https://lh3.googleusercontent.com/small=w320 320w,
                     https://lh3.googleusercontent.com/large=w1280 1280w">
        """

        grouped = extract_rendered_image_refs(html)

        self.assertEqual(
            grouped["lazy-question"][0].url,
            "https://docs.google.com/forms-images-rt/lazy=w640",
        )
        self.assertEqual(
            grouped["srcset-question"][0].url,
            "https://lh3.googleusercontent.com/large=w1280",
        )

    def test_reads_background_image_and_scheme_relative_url(self):
        html = """
        <div data-item-id="background-question"
             style="background-image:url('//docs.google.com/forms-images-rt/bg=w900')">
        </div>
        """

        grouped = extract_rendered_image_refs(html)

        self.assertEqual(
            grouped["background-question"][0].url,
            "https://docs.google.com/forms-images-rt/bg=w900",
        )

    def test_maps_rendered_image_from_data_params_item_id(self):
        html = """
        <div data-params='%.@.[192651193,"question",null]'>
          <img src="https://docs.google.com/forms-images-rt/rendered=w740">
        </div>
        """

        grouped = extract_rendered_image_refs(html)

        self.assertEqual(grouped["192651193"][0].alt_text, "")

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


class MultiPageRenderTests(unittest.TestCase):
    def test_extracts_hidden_navigation_state(self):
        html = """
        <input type="hidden" name="fvv" value="1">
        <input type="hidden" name="partialResponse" value='[[1],null,"abc"]'>
        <input type="hidden" name="pageHistory" value="0,1">
        <input type="hidden" name="fbzx" value="abc">
        """

        state = extract_form_page_state(html)

        self.assertEqual(state["pageHistory"], "0,1")
        self.assertEqual(state["fbzx"], "abc")
        self.assertIn("abc", state["partialResponse"])

    def test_builds_dummy_payloads_for_each_non_image_question(self):
        form_data = [None, [None, [
            [1, "Name", None, 0, [[101, None, 1]]],
            [2, "Class", None, 2, [[102, [["6/1"], ["6/2"]], 1]]],
            [3, "Section", None, 8, None],
            [4, "Image question", None, 0, [[103, None, 1]], None, None, None, None,
             [["s-blob-v1-IMAGE-token", None, [740, 555, 0]]]],
        ]]]

        pages = build_preview_page_payloads(form_data)

        self.assertEqual(pages[0], {"entry.101": "preview", "entry.102": "6/1"})
        self.assertEqual(pages[1], {"entry.103": "preview"})

    def test_finds_only_pages_that_contain_opaque_images(self):
        form_data = [None, [None, [
            [1, "First", None, 0, [[101, None, 1]]],
            [2, "Section", None, 8, None],
            [3, "Image", None, 0, [[102, None, 1]], None, None, None, None,
             [["s-blob-v1-IMAGE-one", None, [740, 555, 0]]]],
            [4, "Section", None, 8, None],
            [5, "Plain", None, 0, [[103, None, 1]]],
        ]]]

        self.assertEqual(find_blob_image_page_indexes(form_data), [1])


if __name__ == "__main__":
    unittest.main()
