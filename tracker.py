"""
tracker.py — Centroid-Based Multi-Object Tracker
=================================================
Assigns persistent IDs to detected bounding boxes across video frames.
"""

import math


class Tracker:
    def __init__(self, max_disappeared: int = 40, dist_threshold: int = 90):
        self.center_points  = {}   # id → (cx, cy)
        self.disappeared    = {}   # id → frames_since_seen
        self.id_count       = 0
        self.max_disappeared = max_disappeared
        self.dist_threshold  = dist_threshold

    def update(self, objects_rect: list) -> list:
        """
        Args:
            objects_rect: list of [x, y, w, h]
        Returns:
            list of [x, y, w, h, track_id]
        """
        result = []

        # Age out disappeared objects
        for oid in list(self.disappeared):
            self.disappeared[oid] += 1
            if self.disappeared[oid] > self.max_disappeared:
                self.center_points.pop(oid, None)
                self.disappeared.pop(oid, None)

        if not objects_rect:
            return result

        for rect in objects_rect:
            x, y, w, h = rect
            cx = x + w // 2
            cy = y + h // 2

            matched_id = None
            min_dist   = float("inf")

            for oid, pt in self.center_points.items():
                dist = math.hypot(cx - pt[0], cy - pt[1])
                if dist < min_dist:
                    min_dist   = dist
                    matched_id = oid

            if matched_id is not None and min_dist < self.dist_threshold:
                self.center_points[matched_id] = (cx, cy)
                self.disappeared[matched_id]   = 0
                result.append([x, y, w, h, matched_id])
            else:
                self.center_points[self.id_count] = (cx, cy)
                self.disappeared[self.id_count]   = 0
                result.append([x, y, w, h, self.id_count])
                self.id_count += 1

        return result
