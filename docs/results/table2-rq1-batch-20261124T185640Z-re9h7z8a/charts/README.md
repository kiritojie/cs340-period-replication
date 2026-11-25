# RQ1 comparison charts

The CSV contains the exact source values; SVG labels are rounded for readability.

Missing runs, invalid-only groups and ND are separate labels. They are never inserted as numeric zero or 10000.
Paper references come from the existing frozen report; paper SD, detection rate and runtime are not invented.
External runtime includes local profiling and supervision overhead; it is not a direct paper timing comparison.

## First error ordinal (detected rounds only)

![First error ordinal (detected rounds only)](first_error_detected_only.svg)

## Total schedules

![Total schedules](total_schedules.svg)

## Error schedules

![Error schedules](error_interleavings.svg)

## Bug detection rate (valid rounds)

![Bug detection rate (valid rounds)](detection_rate.svg)

## External runtime

![External runtime](external_seconds.svg)
