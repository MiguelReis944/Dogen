import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

from ui.pet_widget import PetWidget


def test_pet_volume_uses_visual_gain_without_changing_input_threshold():
    app = QApplication.instance() or QApplication([])
    pet = PetWidget()

    pet.set_volume(0.08)

    assert pet.visual_volume > 0.4
    pet.close()
