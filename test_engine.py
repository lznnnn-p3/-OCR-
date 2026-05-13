# -*- coding: utf-8 -*-
"""Core engine tests - verify template matching, flow execution, JSON I/O"""
import json
import os
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

os.environ["PYTHONIOENCODING"] = "utf-8"

import numpy as np
import cv2
from main import MatchEngine, FlowEngine, Step, Branch, Action


def test_image_matching():
    """Test template matching"""
    print("\n=== Test 1: Template Matching ===")

    # Create a 200x200 "screenshot" with a distinctive pattern
    screenshot = np.zeros((200, 200, 3), dtype=np.uint8)
    # Draw a cross pattern at position (80, 50) that we can match
    cv2.rectangle(screenshot, (80, 50), (130, 100), (0, 200, 0), -1)
    cv2.putText(screenshot, "X", (95, 85), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

    # Create template - a smaller crop of the unique area
    template = screenshot[55:95, 85:125].copy()

    # Use temp dir to avoid path encoding issues
    tmp_dir = tempfile.mkdtemp()
    tmp_path = os.path.join(tmp_dir, "test_template.png")
    cv2.imwrite(tmp_path, template)
    assert os.path.exists(tmp_path), f"Template not saved: {tmp_path}"

    # Test match
    result = MatchEngine.match_template(screenshot, tmp_path, 0.8)
    assert result is not None, "Should match the template"
    cx, cy, conf = result
    print(f"  Match position: ({cx}, {cy}), confidence: {conf:.3f}")
    assert conf > 0.9, f"Confidence should be high, got: {conf}"

    # Test non-match - template of something not in the screenshot
    template_other = np.ones((20, 20, 3), dtype=np.uint8) * 255
    cv2.putText(template_other, "O", (3, 15), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1)
    tmp2_path = os.path.join(tmp_dir, "test_nomatch.png")
    cv2.imwrite(tmp2_path, template_other)

    result2 = MatchEngine.match_template(screenshot, tmp2_path, 0.8)
    assert result2 is None, "Should NOT match unrelated template"
    print("  Non-match correctly returns None")

    # Cleanup
    os.remove(tmp_path)
    os.remove(tmp2_path)
    os.rmdir(tmp_dir)
    print("  [PASS]")


def test_flow_save_load():
    """Test flow JSON serialization"""
    print("\n=== Test 2: Flow Save/Load ===")

    engine = FlowEngine()

    step1 = Step(
        id="step1",
        name="Test Step 1",
        template="templates/test.png",
        threshold=0.85,
        timeout=5.0,
        interval=0.5,
        on_match=Branch(
            actions=[Action(type="click", x=100, y=200, relative="match_center")],
            goto="step2"
        ),
        on_no_match=Branch(
            actions=[Action(type="wait", duration=2.0)],
            goto=""
        )
    )
    step2 = Step(
        id="step2",
        name="Test Step 2",
        template="templates/test2.png",
        threshold=0.75,
        on_match=Branch(
            actions=[
                Action(type="keypress", keys="enter"),
                Action(type="wait", duration=1.0),
                Action(type="click", x=300, y=400)
            ],
            goto=""
        ),
        on_no_match=Branch(goto="step1")
    )

    engine.steps = {"step1": step1, "step2": step2}
    engine.entry_step_id = "step1"

    # Save
    save_path = BASE_DIR / "flows" / "test_flow.json"
    engine.save_flow(str(save_path))
    assert save_path.exists(), "Saved file should exist"
    print(f"  Saved to: {save_path}")

    # Load
    engine2 = FlowEngine()
    engine2.load_flow(str(save_path))
    assert len(engine2.steps) == 2, f"Should have 2 steps, got: {len(engine2.steps)}"
    assert engine2.entry_step_id == "step1"
    assert engine2.steps["step1"].name == "Test Step 1"
    assert engine2.steps["step1"].threshold == 0.85

    # Verify actions
    om = engine2.steps["step1"].on_match
    assert len(om.actions) == 1
    assert om.actions[0].type == "click"
    assert om.actions[0].relative == "match_center"
    assert om.goto == "step2"

    om2 = engine2.steps["step2"].on_match
    assert len(om2.actions) == 3
    assert om2.actions[0].type == "keypress"
    assert om2.actions[0].keys == "enter"

    onm2 = engine2.steps["step2"].on_no_match
    assert onm2.goto == "step1"

    # Cleanup
    os.remove(str(save_path))
    print("  [PASS]")


def test_action_serialization():
    """Test Action dataclass serialization"""
    print("\n=== Test 3: Action Serialization ===")

    actions = [
        Action(type="click", x=100, y=200, relative="match_center"),
        Action(type="wait", duration=3.0),
        Action(type="keypress", keys="ctrl+c"),
        Action(type="typewrite", text="hello"),
        Action(type="scroll", scroll=-3),
        Action(type="drag", x=10, y=20, x2=100, y2=200, duration=0.5),
    ]

    data = [a.__dict__ for a in actions]
    json_str = json.dumps(data, ensure_ascii=False)
    print(f"  JSON length: {len(json_str)} chars")

    restored = [Action(**item) for item in json.loads(json_str)]
    assert len(restored) == len(actions)

    for orig, rest in zip(actions, restored):
        assert orig.type == rest.type
        assert orig.x == rest.x
        assert orig.y == rest.y
        assert orig.relative == rest.relative

    print("  [PASS]")


def test_branch_logic():
    """Test branch logic structure"""
    print("\n=== Test 4: Branch Logic ===")

    engine = FlowEngine()

    engine.steps = {
        "step1": Step(
            id="step1",
            name="Find Main UI",
            template="templates/main.png",
            timeout=10.0,
            interval=1.0,
            on_match=Branch(
                actions=[Action(type="click", x=500, y=300)],
                goto="step2"
            ),
            on_no_match=Branch(
                actions=[Action(type="wait", duration=2.0)],
                goto="step1"
            )
        ),
        "step2": Step(
            id="step2",
            name="Confirm",
            template="templates/confirm.png",
            on_match=Branch(
                actions=[Action(type="keypress", keys="enter")],
                goto=""
            ),
            on_no_match=Branch(
                actions=[Action(type="wait", duration=1.0)],
                goto=""
            )
        )
    }
    engine.entry_step_id = "step1"

    assert engine.steps["step1"].on_match.goto == "step2"
    assert engine.steps["step1"].on_no_match.goto == "step1"
    assert engine.steps["step2"].on_match.goto == ""
    assert engine.steps["step2"].on_no_match.goto == ""

    print("  step1 on_match -> step2")
    print("  step1 on_no_match -> step1 (loop)")
    print("  step2 on_match -> end")
    print("  step2 on_no_match -> end")
    print("  [PASS]")


def test_color_matching():
    """Test color matching"""
    print("\n=== Test 5: Color Matching ===")

    import numpy as np
    from main import MatchEngine

    # Create a 100x100 screenshot with a single red pixel
    screenshot = np.zeros((100, 100, 3), dtype=np.uint8)
    screenshot[50, 30] = [0, 0, 255]  # BGR: red pixel at (30, 50)

    # Should find red pixel
    result = MatchEngine.match_color(screenshot, "#FF0000", 5)
    assert result is not None, "Should find red pixel"
    x, y, conf = result
    assert x == 30 and y == 50, f"Expected (30, 50), got ({x}, {y})"
    assert conf == 1.0
    print(f"  Found red pixel at: ({x}, {y})")

    # Should NOT find blue pixel
    result2 = MatchEngine.match_color(screenshot, "#0000FF", 5)
    assert result2 is None, "Should NOT find blue pixel"
    print("  Blue pixel correctly not found")

    # Test with tolerance
    screenshot[70, 80] = [5, 5, 250]  # close to red, within tolerance
    result3 = MatchEngine.match_color(screenshot, "#FF0000", 10)
    assert result3 is not None, "Should find near-red pixel with tolerance"
    x3, y3, _ = result3
    print(f"  Found near-red pixel at: ({x3}, {y3}) with tolerance 10")

    print("  [PASS]")


def test_color_flow_save_load():
    """Test flow JSON save/load with color match mode"""
    print("\n=== Test 6: Color Flow Save/Load ===")

    from main import FlowEngine, Step, Branch, Action

    engine = FlowEngine()
    step = Step(
        id="color_step",
        name="颜色检测步骤",
        match_mode="color",
        target_color="#00FF00",
        color_tolerance=15,
        timeout=5.0,
        on_match=Branch(
            actions=[Action(type="click", x=0, y=0, relative="match_center")],
            goto=""
        ),
        on_no_match=Branch(
            actions=[Action(type="wait", duration=1.0)],
            goto="color_step"
        )
    )
    engine.steps = {"color_step": step}
    engine.entry_step_id = "color_step"

    save_path = BASE_DIR / "flows" / "test_color_flow.json"
    engine.save_flow(str(save_path))

    engine2 = FlowEngine()
    engine2.load_flow(str(save_path))
    s = engine2.steps["color_step"]
    assert s.match_mode == "color"
    assert s.target_color == "#00FF00"
    assert s.color_tolerance == 15
    assert s.template == ""
    assert s.threshold == 0.8
    assert s.on_match.actions[0].type == "click"

    os.remove(str(save_path))
    print("  [PASS]")


if __name__ == "__main__":
    all_pass = True
    for test in [test_image_matching, test_flow_save_load, test_action_serialization,
                 test_branch_logic, test_color_matching, test_color_flow_save_load]:
        try:
            test()
        except Exception as e:
            print(f"  [FAIL]: {e}")
            import traceback
            traceback.print_exc()
            all_pass = False

    print("\n" + "=" * 50)
    if all_pass:
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED")
        sys.exit(1)
