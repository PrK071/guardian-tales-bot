"""Bounded endpoint selection for observed vertically moving spike columns."""
def crossing_endpoint(features,direction,max_ms,previous_columns=()):
    if direction not in ('left','right') or not features.get('player'):return None
    px,py=features['player'];sign=-1 if direction=='left' else 1
    columns=[e['bbox'][0]+e['bbox'][2]/2 for e in features.get('entities',[]) if e['kind']=='hazard']
    columns+=list(previous_columns)
    ahead=[x for x in columns if -105<(x-px)*sign<550]
    if not ahead:return None
    column=min(ahead,key=lambda x:abs(x-px))
    # Observed full-axis motion: 132 pixels / 300ms in the recorded cave.
    # Stop 150px beyond a column, between columns ~337px apart. The old
    # 900ms pulse could stop directly on the next sweeping column.
    travel=(column-px)*sign+150
    duration=max(160,min(1500,round(travel/.44)))
    if duration>max_ms:return None  # never overrun the observed straight floor
    return {'ms':duration,'strategy':'stop_beyond_observed_spike_column','column_x':column,'desired_travel_pixels':travel,'assumed_pixels_per_ms':.44,'clearance_pixels':150,'collision_free_claim':False}
