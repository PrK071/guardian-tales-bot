"""Separate the recorded solid spike body from transient blue damage text."""
import cv2,numpy as np

def solid_spike(frame,entity):
    if frame is None:return True  # No image is not evidence that a hazard is safe.
    x,y,w,h=entity['bbox'];roi=frame[max(0,y):min(900,y+h),max(0,x):min(1600,x+w)]
    if not roi.size:return True
    hsv=cv2.cvtColor(roi,cv2.COLOR_BGR2HSV)
    blue=cv2.inRange(hsv,(90,35,30),(130,230,165))
    bright=(hsv[:,:,1]<90)&(hsv[:,:,2]>160)
    return bool(np.mean(blue>0)>=.35 and np.mean(bright)<.12)
