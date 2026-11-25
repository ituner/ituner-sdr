"""Automatic RTL HF path selection; RF input wiring must be tested per dongle."""
TUNER_MIN_HZ = 24_000_000


def switch_sampling(library, device, frequency_hz, current=None):
    """Switch before tuning, only when crossing the HF/tuner boundary."""
    desired = 2 if frequency_hz < TUNER_MIN_HZ else 0
    if desired == current:
        return current
    if library.rtlsdr_set_direct_sampling(device, desired) < 0:
        raise RuntimeError('RTL-SDR could not enable ' + ('Q-branch direct sampling' if desired else 'normal tuner sampling'))
    if not desired:
        library.rtlsdr_set_tuner_gain_mode(device, 0)
    print('RTL sampling: ' + ('Q-branch direct sampling (HF input unverified)' if desired else 'normal tuner (VHF/UHF)'), flush=True)
    return desired
