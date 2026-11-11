from app.printfilm_studio.video_prompt_audio import video_prompt_audio


def test_legacy_quoted_dialogue_excludes_adjacent_acting_prose():
    prompt = '传令兵跪在沙地上，用尽最后的力气嘶哑喊出：“关将军急报——襄樊被围……”声音在风沙中撕裂。喊话时身体微微前倾。'
    result = video_prompt_audio(prompt, 'seedance-2.5')
    picture, sound = result.split('\n\n声音执行区：\n')
    assert '声音在风沙中撕裂' in picture and '声音在风沙中撕裂' not in sound
    assert '关将军急报' not in picture
    assert '台词1：{“关将军急报——襄樊被围……”}' in sound
    assert result.count('关将军急报') == 1


def test_structured_dialogue_preserves_speaker_mapping_and_ignores_other_quotes():
    prompt = '画面：门牌写着“军营”。\n运镜：采用“固定镜头”。\n台词：甲：“走！”（语气“急促”）\n台词：乙：“等等。”\n环境声：风声。'
    picture, sound = video_prompt_audio(prompt, 'seedance-2.0').split('\n\n声音执行区：\n')
    assert '台词：甲：〔发声台词1' in picture and '台词：乙：〔发声台词2' in picture
    assert '台词1：“走！”\n台词2：“等等。”' in sound
    assert all(text not in sound for text in ['军营', '固定镜头', '急促'])


def test_no_dialogue_keeps_ambient_audio_without_spoken_language():
    result = video_prompt_audio('画面：人物举简。\n环境声：风声、急促呼吸。\n台词：无', 'seedance-2.5')
    assert '环境声：风声、急促呼吸' in result
    assert '本镜没有指定台词' in result
    assert '台词1' not in result
