//! Unified SPA audio format pod builder.
//!
//! Constructs an SPA audio format pod for PipeWire stream negotiation.
//! Used by both pcm-bridge and signal-gen to create format parameters
//! for `stream.connect()`.

/// Build an SPA audio format pod for stream negotiation as raw bytes.
///
/// Port count in PipeWire is driven by the format params passed to
/// `stream.connect()`, not by the `audio.channels` node property.
/// Without format params, PipeWire defaults to 1 channel regardless
/// of the property value.
///
/// `positions` specifies channel position IDs (e.g. AUX0-AUX7 for playback,
/// MONO for capture). When provided, PipeWire creates per-channel ports that
/// match the target sink/source topology, enabling WirePlumber auto-linking.
/// Pass an empty slice for no position property (pcm-bridge monitor mode).
///
/// The pod is constructed directly in the SPA wire format because the
/// `spa_pod_builder_*` C functions are inline and not exposed by bindgen.
#[allow(non_upper_case_globals)]
pub fn build_audio_format(channels: u32, rate: u32, positions: &[u32]) -> Vec<u8> {
    const SPA_TYPE_Id: u32 = 3;
    const SPA_TYPE_Int: u32 = 4;
    const SPA_TYPE_Array: u32 = 13;
    const SPA_TYPE_Object: u32 = 15;
    const SPA_TYPE_OBJECT_Format: u32 = 0x40003;
    const SPA_PARAM_EnumFormat: u32 = 3;
    const SPA_FORMAT_mediaType: u32 = 1;
    const SPA_FORMAT_mediaSubtype: u32 = 2;
    const SPA_FORMAT_AUDIO_format: u32 = 0x10001;
    const SPA_FORMAT_AUDIO_rate: u32 = 0x10003;
    const SPA_FORMAT_AUDIO_channels: u32 = 0x10004;
    const SPA_FORMAT_AUDIO_position: u32 = 0x10005;
    const SPA_MEDIA_TYPE_audio: u32 = 1;
    const SPA_MEDIA_SUBTYPE_raw: u32 = 1;
    const SPA_AUDIO_FORMAT_F32LE: u32 = 0x11A;

    let mut buf = Vec::with_capacity(200);

    fn write_prop_id(buf: &mut Vec<u8>, key: u32, val: u32) {
        buf.extend_from_slice(&key.to_le_bytes());
        buf.extend_from_slice(&0u32.to_le_bytes());
        buf.extend_from_slice(&4u32.to_le_bytes());
        buf.extend_from_slice(&SPA_TYPE_Id.to_le_bytes());
        buf.extend_from_slice(&val.to_le_bytes());
        buf.extend_from_slice(&[0u8; 4]);
    }

    fn write_prop_int(buf: &mut Vec<u8>, key: u32, val: i32) {
        buf.extend_from_slice(&key.to_le_bytes());
        buf.extend_from_slice(&0u32.to_le_bytes());
        buf.extend_from_slice(&4u32.to_le_bytes());
        buf.extend_from_slice(&SPA_TYPE_Int.to_le_bytes());
        buf.extend_from_slice(&val.to_le_bytes());
        buf.extend_from_slice(&[0u8; 4]);
    }

    let header_pos = buf.len();
    buf.extend_from_slice(&0u32.to_le_bytes());
    buf.extend_from_slice(&SPA_TYPE_Object.to_le_bytes());
    buf.extend_from_slice(&SPA_TYPE_OBJECT_Format.to_le_bytes());
    buf.extend_from_slice(&SPA_PARAM_EnumFormat.to_le_bytes());

    write_prop_id(&mut buf, SPA_FORMAT_mediaType, SPA_MEDIA_TYPE_audio);
    write_prop_id(&mut buf, SPA_FORMAT_mediaSubtype, SPA_MEDIA_SUBTYPE_raw);
    write_prop_id(&mut buf, SPA_FORMAT_AUDIO_format, SPA_AUDIO_FORMAT_F32LE);
    write_prop_int(&mut buf, SPA_FORMAT_AUDIO_rate, rate as i32);
    write_prop_int(&mut buf, SPA_FORMAT_AUDIO_channels, channels as i32);

    if !positions.is_empty() {
        let n = positions.len() as u32;
        let array_data_size = 8 + n * 4;

        buf.extend_from_slice(&SPA_FORMAT_AUDIO_position.to_le_bytes());
        buf.extend_from_slice(&0u32.to_le_bytes());
        buf.extend_from_slice(&array_data_size.to_le_bytes());
        buf.extend_from_slice(&SPA_TYPE_Array.to_le_bytes());
        buf.extend_from_slice(&4u32.to_le_bytes());
        buf.extend_from_slice(&SPA_TYPE_Id.to_le_bytes());
        for &pos in positions {
            buf.extend_from_slice(&pos.to_le_bytes());
        }
        let remainder = (n * 4) % 8;
        if remainder != 0 {
            let pad = 8 - remainder;
            for _ in 0..pad {
                buf.push(0u8);
            }
        }
    }

    let body_size = (buf.len() - header_pos - 8) as u32;
    buf[header_pos..header_pos + 4].copy_from_slice(&body_size.to_le_bytes());

    buf
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn no_positions_size_and_alignment() {
        let pod = build_audio_format(8, 48000, &[]);
        assert_eq!(pod.len() % 8, 0);
        assert_eq!(pod.len(), 136);
    }

    #[test]
    fn header_type() {
        let pod = build_audio_format(2, 44100, &[]);
        let pod_type = u32::from_le_bytes(pod[4..8].try_into().unwrap());
        assert_eq!(pod_type, 15);
    }

    #[test]
    fn body_size() {
        let pod = build_audio_format(3, 48000, &[]);
        let body_size = u32::from_le_bytes(pod[0..4].try_into().unwrap());
        assert_eq!(body_size as usize, pod.len() - 8);
    }

    #[test]
    fn channels_embedded() {
        let pod = build_audio_format(8, 48000, &[]);
        let ch_val = u32::from_le_bytes(pod[128..132].try_into().unwrap());
        assert_eq!(ch_val, 8);
    }

    #[test]
    fn rate_embedded() {
        let pod = build_audio_format(2, 96000, &[]);
        let rate_val = i32::from_le_bytes(pod[104..108].try_into().unwrap());
        assert_eq!(rate_val, 96000);
    }

    #[test]
    fn with_positions_alignment() {
        let pod = build_audio_format(8, 48000, &[0x1000, 0x1001, 0x1002, 0x1003, 0x1004, 0x1005, 0x1006, 0x1007]);
        assert_eq!(pod.len() % 8, 0);
        assert!(pod.len() > 136);
        let body_size = u32::from_le_bytes(pod[0..4].try_into().unwrap());
        assert_eq!(body_size as usize, pod.len() - 8);
    }

    #[test]
    fn mono_position() {
        let pod = build_audio_format(1, 48000, &[0x02]);
        assert_eq!(pod.len() % 8, 0);
        assert!(pod.len() > 136);
    }
}
