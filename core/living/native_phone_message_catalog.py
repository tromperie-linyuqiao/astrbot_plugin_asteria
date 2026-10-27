"""Reviewed local wording for the native phone library's builtin fallback.

The existing 45 greetings stay at each pool's original prefix. These additions
are authored sentences, never random/template combinations or observations of
a screen, conversation, music track or mood. The two Arknights clients share
game wording. The existing message owner consumes this as builtin data;
importing or reading it does not modify user configuration, change override
precedence, generate media, call a model or send.
"""
from __future__ import annotations

import hashlib
import unicodedata

from .models import canonical
from .native_phone_candidates import compile_rules
from .native_phone_messages import DEFAULT_APP_GREETINGS, GREETING_HOUR_GATES

SCHEMA='tls.phone.message_catalog.v1'
MIN_POOL_SIZE=100
MAX_POOL_SIZE=128
MAX_LINE_CHARS=80
RULE_BYTE_BUDGET=65536

_ARKNIGHTS=(
    # Deployment and route planning.
    '部署之前，先看清路线。',
    '留一个位置，应付意外。',
    '高台的视野有时比人数重要。',
    '费用留一点，撤退也要余地。',
    '技能留给需要它的时候。',
    '防线稳了，再考虑向前。',
    '换个落点，思路也会不同。',
    '复杂的路线，可以拆开看。',
    '一支小队，也能把事做好。',
    '先锋的工作，是让后面从容些。',
    '狙击的位置值得多想一步。',
    '医疗跟得上，队伍才走得远。',
    '有些缺口，减速比硬扛合适。',
    '撤回再部署，也是计划的一部分。',
    '守住目标，比追着敌人跑重要。',
    # Operators and team choices.
    '想试谁，就给谁留个位置。',
    '熟悉的干员，配合起来省心。',
    '冷门的组合，有时挺有意思。',
    '阵容顺手，比看起来热闹好。',
    '不同职业，做擅长的事就好。',
    '能互相补位的小队很可靠。',
    '一张地图，可以有几种解法。',
    '干员的天赋，偶尔值得翻一翻。',
    '支援位也是一种选择。',
    '低配的解法，往往藏着巧思。',
    '喜欢的干员，慢慢养也来得及。',
    '练度之外，还有部署顺序。',
    '想换阵容，可以先从一个位置试。',
    '把各自的长处接起来，队伍就完整了。',
    '名单不用很长，配合得上就行。',
    # Base, supplies and optional progression.
    '基建的事，按自己的节奏排。',
    '材料清单写短一点，看着清楚。',
    '仓库里留些余量，之后会方便。',
    '培养计划可以一次只做一项。',
    '贸易站适合安静地运转。',
    '宿舍布置得顺眼，也算一件小事。',
    '想换家具，先留条好走的过道。',
    '基建排班像交接班，清楚就好。',
    '资源攒着，等真正想用的时候。',
    '专精的选择，照常用的小队来。',
    '模组说明有点长，可以慢慢读。',
    '图鉴里有些细节，值得偶尔看看。',
    '养成是长线的事。',
    '任务列表可以分轻重。',
    '能把计划做简单，也是一种本事。',
    # Fiction and atmosphere, without a claim about the current screen.
    '罗德岛的故事，适合慢慢翻。',
    '我喜欢故事里那些安静的片刻。',
    '企鹅物流的名字，听起来总很忙。',
    '龙门的街景，留在画里也不错。',
    '叙拉古的往事，得留些时间读。',
    '比起传闻，我更愿意听完整的故事。',
    '有些人物的选择，值得想一想。',
    '剧情的留白，也有它的分量。',
    '小人物的支线，有时更让人记住。',
    '档案里的一句话，可能藏着另一面。',
    '一段对白，读到合适的地方停就好。',
    '美术里的城市，各有各的气息。',
    '比起结论，我更在意人物怎么走到那里。',
    '喜欢哪段故事，可以以后慢慢说。',
    '故事暂时合上，也还在那里。',
    # Practice and room to stop.
    '演习适合拿来验证想法。',
    '失败的路线，记住原因就够了。',
    '一关卡住，可以换种部署顺序。',
    '攻略能参考，解法也可以自己找。',
    '先试一个思路，比同时改很多处清楚。',
    '愿意复盘时，我听你说。',
    '练熟一支队伍，需要一点时间。',
    '条件变了，计划跟着改就好。',
    '有些挑战，留到准备好再来。',
    '关卡一直在，休息也有位置。',
    '收集可以慢慢来。',
    '抽卡预算，照原先定的就行。',
    '喜欢一个角色，不急着把一切补齐。',
    '拿到想要的结果，记得给自己留点余裕。',
    '停在合适的地方，也算掌握节奏。',
    # Low-pressure conversation prompts.
    '想聊战术，还是聊故事？',
    '有没有想试的职业组合？',
    '你更看重阵容的稳定，还是变化？',
    '哪张地图的设计让你有印象？',
    '想起喜欢的支线，再讲给我听。',
    '干员的立绘和档案，你更喜欢看哪个？',
    '有没有一段配乐，让你记住了场景？',
    '关卡解法这种事，我愿意听。',
    '如果要组主题队，你会选谁？',
    '最顺手的小队，通常有自己的理由。',
    '有想留着慢慢读的剧情吗？',
    '比起强度榜，我想听听你的选择。',
    '一段喜欢的台词，记得大意也行。',
    '今天想轻松玩，还是试点新思路？',
    '罗德岛的事，有空再聊。',
)

_ARKNIGHTS_CHANNEL=(
    '同一片泰拉，可以从不同故事开始。',
    '能记住的小队故事，比名单更长。',
    '熟悉的角色，也会有值得重读的一面。',
)

_MOBA=(
    # Map and objectives.
    '看清兵线，再决定往哪走。',
    '视野多一点，选择就稳一点。',
    '地图上的空白，也值得留意。',
    '目标的先后顺序，可以先想好。',
    '守塔有时比追击划算。',
    '留条退路，行动会从容些。',
    '河道的信息，队伍都用得上。',
    '顺路支援，比绕远追人合适。',
    '转线的时机，比跑得快重要。',
    '兵线处理好了，地图才会宽。',
    '推进需要有人照看侧面。',
    '资源分清轻重，就少些犹豫。',
    '有把握的目标，可以先拿下来。',
    '阵地合适，交手才有余地。',
    '小地图很安静，但信息不少。',
    # Teamwork without judgments about unseen teammates.
    '配合得上，比各打各的省力。',
    '信号简短一点，队友更容易看懂。',
    '开团之前，先等位置到齐。',
    '有人探路，也得有人接应。',
    '支援是一段路，两边都要看。',
    '留一个控制，往往更稳。',
    '前后排的距离，值得留意。',
    '阵容各有职责，接得上就好。',
    '一次撤退，也可以是好配合。',
    '把简单的事做齐，队伍就踏实。',
    '进场的顺序，可以留半拍。',
    '沟通说清要点就够了。',
    '愿意补位的人，值得一句谢谢。',
    '逆风的时候，先让行动一致。',
    '合作的游戏，可靠比热闹重要。',
    # Heroes and roles.
    '想练新英雄，可以从熟悉的位置开始。',
    '擅长的英雄，手感通常有积累。',
    '选顺手的角色，判断会更清楚。',
    '每个位置，都有自己的节奏。',
    '辅助的路线，也能改变一场配合。',
    '边路要算的事，常常不止对线。',
    '打野的路线，可以提前留个备选。',
    '中路的支援，讲究来回的时间。',
    '射手的位置，留得稳些更好。',
    '坦克也需要合适的进场角度。',
    '技能连招，练到顺手就好。',
    '熟悉射程，走位会自然些。',
    '冷却的空当，也是一部分战术。',
    '出装可以根据阵容调整。',
    '英雄的长处，得放在合适的位置。',
    # Learning and concrete review.
    '复盘时，可以只看一个关键决定。',
    '练习场适合试手感。',
    '一段操作，拆开练会清楚些。',
    '判断失误，记住缘由就行。',
    '换个视角看回放，可能有新发现。',
    '把习惯改一点，就已经有进展。',
    '稳定的基本功，很耐用。',
    '新打法可以先试小范围。',
    '有些经验，打过才知道。',
    '想明白一处，比记住十条口诀实在。',
    '胜负之外，还能看看决策。',
    '能解释自己的选择，就更容易调整。',
    '配合的细节，比结果多。',
    '练熟一个时机，需要几次尝试。',
    '遇到新阵容，留点时间适应。',
    # Casual play and personal pace.
    '匹配和排位，照想玩的来。',
    '想轻松一点，也有轻松的玩法。',
    '一局的结果，留在那一局就好。',
    '段位只是游戏里的一项记录。',
    '玩到合适的地方，随时能收。',
    '空出一点时间，游戏也会轻松些。',
    '熟人组队，讲清想玩的方式就好。',
    '单排也可以按自己的计划来。',
    '想换模式，就换个模式。',
    '皮肤选喜欢的，比凑齐更有意思。',
    '预算定好了，选择会简单些。',
    '奖励可以看一看，时间也值得算一算。',
    '娱乐局，开心的标准可以很简单。',
    '输赢都有结束的时候。',
    '休息一下，手感的事之后再说。',
    # Optional conversation.
    '你更喜欢带节奏，还是稳着打？',
    '有没有一直想练的位置？',
    '哪个英雄的设计让你有印象？',
    '如果只选一个技能，你会选哪个？',
    '你喜欢单人判断，还是团队配合？',
    '有值得复盘的一局，再慢慢讲。',
    '地图机制里，你觉得哪处最有意思？',
    '想聊英雄背景，也可以。',
    '比起分数，我更想听有趣的配合。',
    '有什么顺手的小技巧？我听着。',
    '你挑角色时，先看手感还是外形？',
    '最满意的一次判断，不一定是击败对手。',
    '有时一次及时的撤退，也值得记住。',
    '喜欢的模式，可以慢慢摸熟。',
    '游戏里的故事，等有空再说。',
)

_VIDEO=(
    # Film and story.
    '想看长故事，可以留一整段时间。',
    '短片也能把一件事讲完整。',
    '一场好戏，安静看也有意思。',
    '镜头留白的地方，可以多看一眼。',
    '比起剧透，我愿意等故事自己展开。',
    '想找电影，可以从喜欢的题材选。',
    '老片子的节奏，有时很合适。',
    '一个扎实的结尾，值得慢慢等。',
    '角色做选择的时候，故事才真正动起来。',
    '幕后制作也有自己的故事。',
    '同一部作品，重看会有不同发现。',
    '想聊剧情时，先留个不剧透的范围。',
    '有想看的片单，可以慢慢挑。',
    # Documentary and history.
    '纪录片适合一集一集看。',
    '想看远一点的地方，可以选地理题材。',
    '城市的旧影像，常藏着细节。',
    '自然题材里，我喜欢安静的长镜头。',
    '一件器物的来历，也能讲很久。',
    '历史视频的出处，值得顺手看看。',
    '访谈里停顿的部分，有时也重要。',
    '想听完整观点，长访谈更从容。',
    '不同讲述者，会注意到不同细节。',
    '博物馆的展品，隔着镜头也能认识一些。',
    '一条街的变化，可以装下很多故事。',
    '档案和推测，分清了更好看。',
    '喜欢的纪录片，可以留着分段看。',
    # Learning and hands-on interests.
    '教程可以先挑一件真正想学的。',
    '看懂一个步骤，再往下也来得及。',
    '能跟着试的小技巧，比较容易记住。',
    '讲原理的视频，我愿意多听一会儿。',
    '把复杂的事讲清楚，是本事。',
    '想学摄影，可以从构图看起。',
    '修理东西的过程，挺值得看。',
    '手工制作适合慢慢琢磨。',
    '绘画的起稿过程，也有意思。',
    '语言学习的视频，选跟得上的速度就好。',
    '一个知识点讲透，比堆很多更实在。',
    '练习用的素材，简单一点也够。',
    '学到能用的一点，就有收获。',
    # Creative work, animation and craft.
    '动画里的动作设计，很见功夫。',
    '喜欢的画风，可以慢慢认作者。',
    '配音的停顿，能让一句话有不同意思。',
    '剪辑节奏合适，看着会顺。',
    '一段分镜，也能讲清一个场景。',
    '原画和成片放在一起看，很有意思。',
    '想换点口味，可以看看独立短片。',
    '有些二创，认真得像另一封回信。',
    '音乐现场的编排，也值得留意。',
    '舞台后的排练，比想象中细。',
    '一个好点子，短短几分钟也放得下。',
    '特效之外，构思也很重要。',
    '喜欢一段作品，记住作者也不错。',
    # Food, places and everyday curiosities.
    '家常菜的做法，简单一些更实用。',
    '烘焙的步骤，像一份耐心的说明。',
    '地方小吃的来历，听着也有意思。',
    '看做饭过程，刀工只是其中一部分。',
    '一锅汤的讲究，能聊不少。',
    '旅行视频里，小路常比景点安静。',
    '想认识一座城，可以先看看街巷。',
    '火车窗外的风景，适合慢镜头。',
    '旧书店的巡游视频，我会留意。',
    '看人修一件旧物，也算一段旅程。',
    '建筑的细节，换个角度更清楚。',
    '普通的一天，认真记录也有内容。',
    '喜欢哪种日常题材，可以慢慢找。',
    # Choosing at one's own pace.
    '想好一个题材，挑选会容易些。',
    '收藏是备选，什么时候看都可以。',
    '长视频可以留个合适的停点。',
    '看完一段，再决定要不要接着看。',
    '遇到想细看的地方，可以暂停。',
    '看熟悉的作品，也是一种选择。',
    '推荐很多，合眼缘的一部就够。',
    '字幕清楚，长内容会好跟一些。',
    '安静的题材，也能很丰富。',
    '轻松一点的内容，选自己喜欢的就好。',
    '一部作品的篇幅，不决定它的分量。',
    '想看的清单，可以留点空位。',
    '这一段看完，之后的事再安排。',
    # Conversation without claiming to know the current feed.
    '你喜欢镜头多一点，还是讲述多一点？',
    '最近想了解哪个题材？',
    '有什么一直想看的老片？',
    '比起排行榜，我想听你的推荐理由。',
    '有没有哪种讲解风格特别合适？',
    '如果挑一部纪录片，你会选什么方向？',
    '喜欢的片段，讲个大意也行。',
    '你更在意故事，还是画面？',
    '一段好的开场，通常怎么吸引你？',
    '看到愿意重看的作品，再聊给我听。',
    '想看热闹的，还是安静的题材？',
    '有值得留意的作者，可以记下名字。',
    '今天的片单，留给你自己选。',
)

_MUSIC=(
    # Style and arrangements.
    '想换个风格，可以从编曲选。',
    '原声乐器的质感，值得慢慢听。',
    '简洁的伴奏，也能把旋律托住。',
    '爵士里的空拍，我觉得挺有意思。',
    '摇滚的力度，也可以很有分寸。',
    '民谣适合把故事讲近一点。',
    '电子乐里的层次，可以一点点找。',
    '纯音乐留出的空间比较多。',
    '想听现场，可以挑收音清楚的版本。',
    '同一段旋律，换种编配会不同。',
    '小编制的声音，常常很清楚。',
    '喜欢复古一点的音色吗？',
    '一首歌的节奏，可以慢慢认识。',
    # Instruments and sound.
    '低音线走得稳，整首会踏实。',
    '鼓点之间的停顿，也有节奏。',
    '钢琴的尾音，可以多留一会儿。',
    '弦乐的铺陈，适合耐心听。',
    '吉他的拨弦声，有自己的颗粒。',
    '铜管一进来，画面感会变。',
    '木管的音色，很适合安静的旋律。',
    '人声的呼吸，也是演唱的一部分。',
    '合声安排得好，旋律会更宽。',
    '贝斯有时值得单独留意。',
    '手风琴的声音，容易让人记住。',
    '留白比堆满声音更难把握。',
    '乐器少一点，也能把故事讲全。',
    # Choosing and revisiting.
    '熟悉的专辑，重听也会有细节。',
    '想听完整一些，可以按专辑顺序来。',
    '旧歌适合偶尔翻出来。',
    '新的声音，可以先听一首。',
    '歌单留点空位，之后慢慢补。',
    '想换个开场，可以从前奏挑。',
    '短一点的曲子，也有完整的起落。',
    '一张专辑的结尾，常有自己的安排。',
    '不同年代的录音，各有质感。',
    '想听冷门一点的，可以从制作人找。',
    '翻唱和原唱，可以各听各的意思。',
    '重制版和旧版，喜欢哪个都行。',
    '有些旋律，隔一阵再听正合适。',
    # Composition and craft.
    '好前奏能把空间慢慢打开。',
    '副歌之外，过渡也值得听。',
    '旋律回来的时候，可以留意变化。',
    '配乐有自己的叙事方式。',
    '游戏原声，也适合当作品听。',
    '电影配乐离开画面，会有另一种感觉。',
    '一段动机，能串起很长的作品。',
    '歌词的留白，有时比解释更耐听。',
    '节拍变换得自然，是细功夫。',
    '声音的位置，也属于编曲。',
    '一段间奏，可以是整首的转弯。',
    '录音里的小细节，耳机能听清一些。',
    '写得克制的歌，也可能留得久。',
    # Atmosphere, framed as choices rather than mood facts.
    '想让背景安静些，可以选稀疏的编曲。',
    '做别的事时，纯音乐也是个选项。',
    '走路听什么，照自己的步子选。',
    '雨声配乐，喜欢的话可以留一首。',
    '想换点清爽的声音，可以听木吉他。',
    '想听宽一点的场面，可以挑管弦乐。',
    '一段不赶时间的旋律，也挺好。',
    '需要留心周围时，声音轻一点合适。',
    '背景里的音乐，简单些也够。',
    '独奏和合奏，可以换着听。',
    '想把一首听完整，就留点空闲给它。',
    '音乐可以陪一段路，也可以安静结束。',
    '歌停下来，余韵还能留一会儿。',
    # Discovery without inspecting private playlists or a current track.
    '想找新歌，可以从喜欢的乐器开始。',
    '有时候，同厂牌会藏着相近的声音。',
    '专辑制作名单里，也有发现新作品的路。',
    '一场小型现场，可能认识新的乐队。',
    '熟悉的歌手，也可以听听早期作品。',
    '想听别的语言，可以先从旋律接近的找。',
    '配乐作者的独立作品，也值得留意。',
    '一首合作曲，可能通向另一位音乐人。',
    '地域不同，节奏的习惯也不同。',
    '想听器乐，可以按独奏乐器挑。',
    '找到喜欢的音色，比追更新从容。',
    '一份歌单，按主题整理会清楚些。',
    '遇到喜欢的作品，记下作者就好。',
    # Optional conversation, never a claim about what is playing.
    '你选歌时，先听旋律还是人声？',
    '有没有一张愿意从头听到尾的专辑？',
    '想聊哪种乐器？',
    '你更喜欢录音室版，还是现场版？',
    '如果只留一段前奏，你会选哪段？',
    '有愿意推荐的歌，再告诉我名字。',
    '一句喜欢的歌词，聊大意也可以。',
    '你会因为一段配乐去认识作品吗？',
    '什么样的鼓点最合你的节奏？',
    '有哪种音色，一听就能认出来？',
    '想听老作品，还是找新声音？',
    '歌的长短，对你重要吗？',
    '挑一首你想讲的，我听你说。',
)

_ADDITIONS={
    'com.hypergryph.arknights':_ARKNIGHTS,
    'com.hypergryph.arknights.bilibili':_ARKNIGHTS+_ARKNIGHTS_CHANNEL,
    'com.tencent.tmgp.sgame':_MOBA,
    'tv.danmaku.bili':_VIDEO,
    'com.netease.cloudmusic':_MUSIC,
}


def _merged():
    return {package:[*DEFAULT_APP_GREETINGS[package],*additions] for package,additions in _ADDITIONS.items()}


def validate_catalog(catalog,*,byte_budget=RULE_BYTE_BUDGET):
    """Validate the complete reviewed extension and report actual UTF-8 costs.

    This validates authored baseline data, not user custom/remote overrides.
    It rejects duplicates and excess data; it never truncates or rewrites text.
    ``candidate_rules_bytes`` includes the real compiler's lines/hour metadata,
    matching the existing candidate policy's 64 KiB total configuration bound.
    """
    if type(byte_budget) is not int or not 1<=byte_budget<=RULE_BYTE_BUDGET:
        raise ValueError('bounded catalog byte budget required')
    if not isinstance(catalog,dict) or set(catalog)!=set(_ADDITIONS):
        raise ValueError('complete five-app catalog required')
    counts={};message_bytes=0;maximum=0
    for package,lines in catalog.items():
        prefix=DEFAULT_APP_GREETINGS[package]
        if not isinstance(lines,(list,tuple)) or not MIN_POOL_SIZE<=len(lines)<=MAX_POOL_SIZE:
            raise ValueError('catalog pool must contain 100 to 128 messages')
        if tuple(lines[:len(prefix)])!=prefix:raise ValueError('original greeting prefix changed')
        seen=set()
        for line in lines:
            if (not isinstance(line,str) or not line or line!=line.strip() or len(line)>MAX_LINE_CHARS
                    or any(ord(char)<32 or ord(char)==127 for char in line)):
                raise ValueError('short plain catalog sentence required')
            identity=unicodedata.normalize('NFKC',line).casefold()
            if identity in seen:raise ValueError('duplicate catalog sentence')
            seen.add(identity);message_bytes+=len(line.encode('utf-8'));maximum=max(maximum,len(line))
        counts[package]=len(lines)
    rules=compile_rules(catalog,hour_gates=GREETING_HOUR_GATES)
    raw=canonical(catalog).encode('utf-8');rule_bytes=len(canonical(rules).encode('utf-8'))
    if rule_bytes>byte_budget:raise ValueError('catalog candidate rules exceed byte budget')
    return dict(schema=SCHEMA,app_counts=counts,total_messages=sum(counts.values()),
        original_prefix_messages=sum(map(len,DEFAULT_APP_GREETINGS.values())),
        message_utf8_bytes=message_bytes,catalog_bytes=len(raw),candidate_rules_bytes=rule_bytes,
        byte_budget=byte_budget,remaining_bytes=byte_budget-rule_bytes,max_line_chars=maximum,
        sha256=hashlib.sha256(raw).hexdigest())


def expanded_catalog():
    """Return detached builtin data; the original literal prefixes stay intact."""
    catalog=_merged();validate_catalog(catalog);return catalog


def catalog_stats():
    """Describe the complete extension without installing it or exposing state."""
    return validate_catalog(_merged())
