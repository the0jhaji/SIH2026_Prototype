from pipeline.detections import Box, ObjectDetection
from pipeline.hand import pixel_distance
from pipeline.interaction.geometry import centre_inside_box, hand_proximity, object_diagonal
from pipeline.interaction.demo import make_hand

FRAME = (640, 480)
RED_BOX = Box(100, 100, 80, 60)  # diagonal = 100 px


def _det(class_name: str, box: Box, conf: float = 0.9) -> ObjectDetection:
    return ObjectDetection(class_name=class_name, confidence=conf, bounding_box=box, timestamp=1)


def test_object_diagonal() -> None:
    assert object_diagonal(RED_BOX) == 100.0


def test_pixel_distance_touching() -> None:
    # Fingertips at the box centre → 0 px.
    hand = make_hand(RED_BOX.cx / FRAME[0], RED_BOX.cy / FRAME[1])
    assert pixel_distance(hand, RED_BOX, FRAME) == 0.0


def test_hand_proximity_on_off() -> None:
    near = hand_proximity(
        0, make_hand(RED_BOX.cx / FRAME[0], RED_BOX.cy / FRAME[1]), RED_BOX, FRAME, near_mult=0.9
    )
    assert near.near and near.distance_px == 0.0
    far = hand_proximity(0, make_hand(0.05, 0.05), RED_BOX, FRAME, near_mult=0.9)
    assert not far.near
    assert far.distance_px > 0.9 * object_diagonal(RED_BOX)  # well outside envelope


def test_proximity_scales_with_object_diagonal() -> None:
    big = Box(100, 100, 400, 300)  # diagonal 500 px, centre (300, 250)
    hand = make_hand(600 / 640, 400 / 480)  # fingertips at (600, 400)
    assert hand_proximity(0, hand, big, FRAME, near_mult=0.9).near      # 335 ≤ 450
    assert not hand_proximity(0, hand, RED_BOX, FRAME, near_mult=0.9).near  # 533 > 90


def test_centre_inside_box_with_margin() -> None:
    box = Box(300, 300, 200, 150)
    assert centre_inside_box((400, 375), box, margin_ratio=0.0)
    assert not centre_inside_box((500, 500), box, margin_ratio=0.0)
    assert centre_inside_box((540, 490), box, margin_ratio=0.2)


def test_events_carry_contract_fields() -> None:
    from pipeline.interaction.events import InteractionEvent

    ev = InteractionEvent(name="RED_PLACED", object_class="red_box", timestamp=1, confidence=0.9)
    data = ev.to_dict()
    assert data["name"] == "RED_PLACED"
    assert data["object"] == "red_box"
    assert set(data) >= {"name", "object", "confidence", "timestamp"}