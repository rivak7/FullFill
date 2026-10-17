"""Take test and reference photos through the station camera.

    python -m eval.capture eval/photos t2_          # order photos: t2_01.jpg, t2_02.jpg, ...
    python -m eval.capture data/references/ranch_cup ref_

Space saves a photo, q quits. Photos are cropped to MAT_ROI like a real check.
Take references and test photos from the same mount; don't move it in between.
"""
import sys
from pathlib import Path

import cv2

import config


def next_path(folder, prefix):
    n = 1
    while (folder / f"{prefix}{n:02d}.jpg").exists():
        n += 1
    return folder / f"{prefix}{n:02d}.jpg"


def crop(frame):
    if config.MAT_ROI is None:
        return frame
    x, y, w, h = config.MAT_ROI
    return frame[y:y + h, x:x + w]


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    folder, prefix = Path(sys.argv[1]), sys.argv[2]
    folder.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(config.CAMERA_INDEX)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.FRAME_HEIGHT)
    if not cap.isOpened():
        sys.exit(f"can't open camera {config.CAMERA_INDEX}; try CAMERA_INDEX=1")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                continue
            frame = crop(frame)
            cv2.imshow("capture (space = save, q = quit)", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord(" "):
                path = next_path(folder, prefix)
                cv2.imwrite(str(path), frame)
                print(f"saved {path}")
            elif key == ord("q"):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
