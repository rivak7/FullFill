import cv2

for i in range(4):
    cap = cv2.VideoCapture(i)
    ok, frame = cap.read()
    if ok:
        cv2.imwrite(f"camera_{i}.jpg", frame)
        print(i, frame.shape)
    cap.release()
