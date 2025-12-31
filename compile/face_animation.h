// face_animation.h - 完整的面部表情动画系统
// 完全从 test.py 移植，所有参数和逻辑保持一致
// 特点：idle 自动执行（眨眼、眼球移动、嘴巴卖萌），情绪模式通过 EXPR:xxx 指令切换

#ifndef FACE_ANIMATION_H
#define FACE_ANIMATION_H

#include <Arduino.h>

// ==================== 舵机通道定义 ====================
// 嘴巴舵机（新增 4 通道）
#define CH_MOUTH_R     0    // 右嘴角 (80上/咧 - 100下/撇, 中立90)
#define CH_MOUTH_L     1    // 左嘴角 (105上/咧 - 85下/撇, 中立95)
#define CH_MOUTH_U     2    // 上嘴唇 (75上 - 104下, 中立90)
#define CH_MOUTH_LOWER 3    // 下嘴唇开合 (85闭 - 140张)

// 其他舵机
#define CH_WING_A      5    // 翅膀A (低垂60 - 高起150)
#define CH_WING_B      6    // 翅膀B (低垂120 - 高起30，反向)
#define CH_BUTT        7    // 屁股 (低垂100 - 翘起0，反向)
#define CH_EYE_UD      8    // 眼睛上下 (范围 60-120)
#define CH_MOUTH       9    // 嘴巴旧通道（保留兼容，实际用 CH_MOUTH_LOWER）
#define CH_EYE_LR_L   10    // 眼球左右(左) (范围 30-140)
#define CH_EYE_LR_R   11    // 眼球左右(右) (范围 30-140)
#define CH_EYELID_L   12    // 眼皮眨眼(左)
#define CH_EYELID_R   13    // 眼皮眨眼(右)
#define CH_LID_ROT_L  14    // 眼皮旋转(左)
#define CH_LID_ROT_R  15    // 眼皮旋转(右)

// ==================== 舵机角度限制 ====================
#define EYE_UD_MIN     60
#define EYE_UD_MAX    120
#define EYE_LR_MIN     30
#define EYE_LR_MAX    140
#define MOUTH_CLOSED   35
#define MOUTH_MAX_OPEN 85

// ==================== 新嘴巴舵机角度限制 ====================
// ★ 根据实际硬件微调

// 右嘴角 CH0: 75(上扬/咧开) - 100(下弯/撇嘴), 中立90
#define MOUTH_R_UP      75
#define MOUTH_R_NEUTRAL 90
#define MOUTH_R_DOWN    100

// 左嘴角 CH1: 110(上扬/咧开) - 85(下弯/撇嘴), 中立95
#define MOUTH_L_UP      110
#define MOUTH_L_NEUTRAL 95
#define MOUTH_L_DOWN    85

// 上嘴唇 CH2: 75(最上) - 112(最下), 中立90
#define MOUTH_U_UP      75
#define MOUTH_U_NEUTRAL 90
#define MOUTH_U_DOWN    112

// 下嘴唇 CH3: 85(闭) - 140(张)
// ★ 全范围使用，运动范围大
#define MOUTH_LOWER_CLOSED  85
#define MOUTH_LOWER_NEUTRAL 100
#define MOUTH_LOWER_OPEN    140

// ==================== 元音嘴型定义 ====================
// 每个元音对应 4 个舵机的目标角度
// ★ 更新后的范围：
//   右嘴角 CH0: 75(咧开) - 100(撇嘴), 中立90
//   左嘴角 CH1: 110(咧开) - 85(撇嘴), 中立95
//   上嘴唇 CH2: 75(最上) - 112(最下), 中立90
//   下嘴唇 CH3: 85(闭) - 140(张)，全范围大幅运动
struct MouthShape {
  int rightCorner;  // 右嘴角 (80-100)
  int leftCorner;   // 左嘴角 (85-105)
  int upperLip;     // 上嘴唇 (75-104)
  int lowerLip;     // 下嘴唇 (85-140)
};

// ==================== 中文元音嘴型表 - 最大幅度版 ====================
// ★ 确保下嘴唇从 85 充分运动到 140
// ★ 上嘴唇使用全范围 (75~112)
// ★ 嘴角充分运动

// 'A' 啊 - 大张嘴，嘴角大咧，上嘴唇上抬，下嘴唇全开
// 'O' 哦 - 圆嘴，嘴角向中收，上嘴唇下压，下嘴唇半开
// 'E' 呃 - 半开，嘴角略咧，中等开口
// 'I' 衣 - 扁嘴，嘴角大咧，上嘴唇上抬，下嘴唇微张
// 'U' 乌 - 嘟嘴，嘴角收紧撇嘴，上嘴唇大幅下压
//                        右嘴角(75-100) 左嘴角(85-110) 上嘴唇(75-112) 下嘴唇(85-140)
const MouthShape MOUTH_SHAPE_A = {75, 110, 75, 140};      // 啊 - 大张嘴！嘴角全咧
const MouthShape MOUTH_SHAPE_O = {94, 91, 105, 118};      // 哦 - 圆嘴，嘴角收，上嘴唇下压
const MouthShape MOUTH_SHAPE_E = {82, 103, 82, 110};      // 呃 - 半开
const MouthShape MOUTH_SHAPE_I = {75, 110, 78, 95};       // 衣 - 扁嘴大咧，下嘴唇微张
const MouthShape MOUTH_SHAPE_U = {98, 87, 107, 100};      // 乌 - 嘟嘴撇嘴，上嘴唇下压
const MouthShape MOUTH_SHAPE_CLOSED = {90, 95, 90, 85};   // 闭嘴 - 中立位

// ==================== 表情嘴型定义 ====================
// 用于不同表情的嘴部姿态（下嘴唇 85闭-140开）
// ★ 参数说明：{右嘴角(75-100), 左嘴角(85-110), 上嘴唇(75-112), 下嘴唇(85-140)}
// ★ 右嘴角 CH0: 75=上扬咧开, 100=下弯撇嘴
// ★ 左嘴角 CH1: 110=上扬咧开, 85=下弯撇嘴
// ★ 上嘴唇 CH2: 75=上扬, 112=下压
// ★ 下嘴唇: 85=闭, 140=大张

// 生气：★ 歪嘴效果 - 右嘴角上扬(75)，左嘴角下弯(85)，形成不对称
// 上嘴唇会在动画中来回抽动，这里设置基准值
const MouthShape MOUTH_EXPR_ANGRY = {75, 85, 105, 95};

// 开心：嘴角全咧开(75,110)，上嘴唇上扬(78)，微笑张嘴
// ★ 上嘴唇往上扬，露出开心表情
const MouthShape MOUTH_EXPR_HAPPY = {75, 110, 78, 115};

// 悲伤：★ 不歪嘴 - 两边嘴角都压到最低(100, 85)
// 上嘴唇向下压(110)，形成委屈/沮丧的表情
const MouthShape MOUTH_EXPR_SAD = {100, 85, 110, 88};

// 无语：★ 歪嘴效果（和生气类似）- 右嘴角上扬(75)，左嘴角下弯(85)
// 上嘴唇下压(108)，静止不抽动
const MouthShape MOUTH_EXPR_SPEECHLESS = {75, 85, 108, 90};

// wink俏皮：★ 单边咧嘴 - 右嘴角大咧(75)，左嘴角略收(100)，上嘴唇上扬(80)，微张嘴
const MouthShape MOUTH_EXPR_WINK = {75, 100, 80, 102};

// ==================== 翅膀和屁股角度 ====================
// CH5 右翅膀: 40(上) - 120(下), 中立90, 限位 40-120
#define WING_A_NEUTRAL  90    // 翅膀A(右)中立位
#define WING_A_LOW     120    // 翅膀A(右)最低（不超过此值）
#define WING_A_HIGH     40    // 翅膀A(右)最高
// CH6 左翅膀: 140(上) - 60(下), 中立90, 限位 60-140
#define WING_B_NEUTRAL  90    // 翅膀B(左)中立位
#define WING_B_LOW      60    // 翅膀B(左)最低（不超过此值）
#define WING_B_HIGH    140    // 翅膀B(左)最高
// CH7 屁股: 40(翘起) - 90(低垂), 限位 40-90
#define BUTT_NEUTRAL    75    // 屁股中立位（稍微低一点）
#define BUTT_LOW        90    // 屁股最低
#define BUTT_HIGH       40    // 屁股最高（翘起）

// ==================== 眼皮角度 ====================
#define EYELID_L_CLOSED    50
#define EYELID_L_NORMAL   110
#define EYELID_L_MAX_OPEN 130

#define EYELID_R_CLOSED   130
#define EYELID_R_NORMAL    70
#define EYELID_R_MAX_OPEN  50

// ==================== 眼皮旋转角度 ====================
#define LID_ROT_L_ANGRY    60
#define LID_ROT_L_NORMAL   85
#define LID_ROT_L_SAD     110

#define LID_ROT_R_ANGRY   120
#define LID_ROT_R_NORMAL   95
#define LID_ROT_R_SAD      70

// ==================== 全局速度倍数（可调节）====================
// 值越大，动画越慢。1.0 = 原速，2.0 = 慢一倍
#define ANIM_SPEED_MULTIPLIER     1.5f    // 加快一点

// ==================== 眨眼参数 ====================
// 眨眼间隔固定 2-4 秒，不受速度倍数影响
#define BLINK_INTERVAL_MIN_MS      2000   // 最短 2 秒
#define BLINK_INTERVAL_MAX_MS      4000   // 最长 4 秒
#define BLINK_CLOSE_DURATION_MS      100  // 闭眼时间（使用贝塞尔曲线渐变）
#define BLINK_OPEN_DURATION_MS       100  // 睁眼时间（使用贝塞尔曲线渐变）

// ==================== 眼皮微动参数 ====================
#define EYELID_JITTER_MIN         -10
#define EYELID_JITTER_MAX          10
#define EYELID_JITTER_INTERVAL_MIN (int)(120 * ANIM_SPEED_MULTIPLIER)
#define EYELID_JITTER_INTERVAL_MAX (int)(350 * ANIM_SPEED_MULTIPLIER)
#define EYELID_LOOKUP_THRESHOLD   0.7f
#define EYELID_LOOKDOWN_THRESHOLD 0.3f

// ==================== 眼球移动参数（极简版）====================
// 设计：半秒微动一次，几秒大动一次
// 眼球范围：UD=60-120(60度), LR=30-140(110度)

// 微动参数（频繁小幅度移动）
#define EYE_MICRO_INTERVAL_MIN    300    // 微动间隔最短 0.3 秒 - 加快
#define EYE_MICRO_INTERVAL_MAX    500    // 微动间隔最长 0.5 秒 - 加快
#define EYE_MICRO_MOVE_TIME       150    // 微动移动时间 0.15 秒 - 加快
#define EYE_MICRO_AMP_UD          12     // 上下微动幅度（度）
#define EYE_MICRO_AMP_LR          18     // 左右微动幅度（度）

// 大动参数（行程的1/2到2/3）
#define EYE_BIG_MOVE_INTERVAL_MIN 2500   // 大动间隔最短 2.5 秒 - 加快
#define EYE_BIG_MOVE_INTERVAL_MAX 5000   // 大动间隔最长 5 秒 - 加快
#define EYE_BIG_MOVE_TIME_MIN     250    // 大动移动时间最短 0.25 秒 - 加快
#define EYE_BIG_MOVE_TIME_MAX     400    // 大动移动时间最长 0.4 秒 - 加快
#define EYE_BIG_AMP_UD            30     // 上下大动幅度（度）
#define EYE_BIG_AMP_LR            55     // 左右大动幅度（度）

// 斜向移动参数（水平+垂直同时大幅移动）
#define EYE_DIAGONAL_PROB         0.35f  // 大动时斜向移动的概率（35%）
#define EYE_DIAGONAL_AMP_UD       25     // 斜向上下幅度（度）
#define EYE_DIAGONAL_AMP_LR       45     // 斜向左右幅度（度）

// 眼球范围
#define EYE_CENTER_UD             95     // 上下中心位置（稍微偏上）
#define EYE_CENTER_LR             85     // 左右中心位置
#define EYE_UP_BIAS               0.7f   // 往上看的偏好 (0.5=均匀, 0.7=70%往上, 0.3=30%往上)

// ==================== 嘴巴卖萌参数 ====================
#define MOUTH_CUTE_PROB        0.20f    // 触发概率
#define MOUTH_CUTE_BLINK_PROB  0.40f    // 眨眼时卖萌概率
#define MOUTH_CUTE_INTERVAL_MIN 3000    // 最短 3 秒
#define MOUTH_CUTE_INTERVAL_MAX 8000    // 最长 8 秒

#define MOUTH_SLOW_OPEN_MIN     (int)(400 * ANIM_SPEED_MULTIPLIER)
#define MOUTH_SLOW_OPEN_MAX     (int)(800 * ANIM_SPEED_MULTIPLIER)
#define MOUTH_SLOW_AMOUNT_MIN  0.4f
#define MOUTH_SLOW_AMOUNT_MAX  0.8f
#define MOUTH_FAST_CLOSE        (int)(80 * ANIM_SPEED_MULTIPLIER)
#define MOUTH_HOLD_OPEN_MIN     (int)(100 * ANIM_SPEED_MULTIPLIER)
#define MOUTH_HOLD_OPEN_MAX     (int)(300 * ANIM_SPEED_MULTIPLIER)

#define MOUTH_FLAP_COUNT_MIN      2
#define MOUTH_FLAP_COUNT_MAX      4
#define MOUTH_FLAP_DURATION      (int)(60 * ANIM_SPEED_MULTIPLIER)
#define MOUTH_FLAP_AMOUNT_MIN  0.3f
#define MOUTH_FLAP_AMOUNT_MAX  0.6f

// ==================== 情绪模式参数 ====================
#define EMOTION_TRANS_MS       (int)(1000 * ANIM_SPEED_MULTIPLIER)
#define ANGRY_EYELID_L           80
#define ANGRY_EYELID_R          100
#define ANGRY_DURATION_MIN     (int)(3000 * ANIM_SPEED_MULTIPLIER)
#define ANGRY_DURATION_MAX     (int)(5000 * ANIM_SPEED_MULTIPLIER)

#define SAD_EYELID_L             85
#define SAD_EYELID_R             95
#define SAD_EYE_DOWN_PROB      0.7f
#define SAD_DURATION_MIN       (int)(4000 * ANIM_SPEED_MULTIPLIER)
#define SAD_DURATION_MAX       (int)(6000 * ANIM_SPEED_MULTIPLIER)

// Happy 表情：睁大眼睛 + 开心的嘴
#define HAPPY_EYELID_L          EYELID_L_MAX_OPEN   // 睁大眼睛（130）
#define HAPPY_EYELID_R          EYELID_R_MAX_OPEN   // 睁大眼睛（50）
#define HAPPY_ROT_L              65
#define HAPPY_ROT_R             115
#define HAPPY_ROT_SWING          10
#define HAPPY_MOUTH_OPEN         75
#define HAPPY_DURATION_MIN     (int)(3000 * ANIM_SPEED_MULTIPLIER)
#define HAPPY_DURATION_MAX     (int)(5000 * ANIM_SPEED_MULTIPLIER)

#define SPEECHLESS_EYELID_L      65
#define SPEECHLESS_EYELID_R     115
#define SPEECHLESS_EYE_UP       115
#define SPEECHLESS_DURATION_MIN (int)(2000 * ANIM_SPEED_MULTIPLIER)
#define SPEECHLESS_DURATION_MAX (int)(4000 * ANIM_SPEED_MULTIPLIER)

// Wink 眨眼时间增大，确保在更新间隔内能被检测到
#define WINK_CLOSE_MS            250    // 闭眼时间（不受速度倍数影响，确保可见）
#define WINK_OPEN_MS             200    // 睁眼时间
#define WINK_COUNT_MIN            1
#define WINK_COUNT_MAX            2
#define WINK_EYE_TURN            35
#define WINK_MOUTH_COUNT          2
#define WINK_MOUTH_MS           (int)(150 * ANIM_SPEED_MULTIPLIER)
#define WINK_DURATION_MIN      (int)(2000 * ANIM_SPEED_MULTIPLIER)
#define WINK_DURATION_MAX      (int)(3000 * ANIM_SPEED_MULTIPLIER)

// ==================== 翅膀和屁股动作参数 ====================
// 呼吸感微动参数（小幅度、缓慢、随机）
#define BREATH_CYCLE_MIN       2000     // 呼吸周期最短 2 秒
#define BREATH_CYCLE_MAX       4000     // 呼吸周期最长 4 秒
#define BREATH_PAUSE_PROB      0.25f    // 呼吸暂停概率（25%概率停一会）
#define BREATH_PAUSE_MIN       1000     // 暂停最短 1 秒
#define BREATH_PAUSE_MAX       3000     // 暂停最长 3 秒
#define WING_BREATH_AMP        12       // 翅膀呼吸幅度（中立位±12度）
#define BUTT_BREATH_AMP        8        // 屁股呼吸幅度（中立位±8度）

// 偶尔的大动作参数
#define BIG_ACTION_PROB        0.35f    // 大动作触发概率（35%）
#define BIG_ACTION_INTERVAL_MIN 5000    // 大动作间隔最短 5 秒
#define BIG_ACTION_INTERVAL_MAX 12000   // 大动作间隔最长 12 秒

// 翅膀扑腾（大动作）
#define WING_FLAP_DURATION     200      // 翅膀扑腾单次时间（平滑一点）
#define WING_FLAP_COUNT_MIN    2        // 扑腾次数最少
#define WING_FLAP_COUNT_MAX    3        // 扑腾次数最多
#define WING_FLAP_AMP          35       // 扑腾幅度（从中立位）

// 屁股翘起（大动作）
#define BUTT_UP_DURATION       250      // 屁股上翘时间（平滑）
#define BUTT_DOWN_DURATION     400      // 屁股下降时间（更平滑）
#define BUTT_HOLD_DURATION     150      // 屁股在上面停留时间
#define BUTT_WIGGLE_COUNT_MIN  1        // 扭动次数最少
#define BUTT_WIGGLE_COUNT_MAX  2        // 扭动次数最多
#define BUTT_WIGGLE_AMP        25       // 翘起幅度（从中立位）

// ==================== 离线随机表情参数 ====================
#define OFFLINE_EXPR_INTERVAL_MIN 8000   // 离线时随机表情间隔最短 8 秒
#define OFFLINE_EXPR_INTERVAL_MAX 18000  // 离线时随机表情间隔最长 18 秒
#define OFFLINE_EXPR_PROB         0.75f  // 75% 概率播放表情，25% 继续 idle

// ==================== 脖子舵机随机微动参数 ====================
// 脖子使用 SCServo 总线舵机（ID 1-4）
// ID 1: 左右旋转 (1050-3000, 中点2025)
// ID 2: 前后俯仰 (1500-2500, 中点2047)
// ID 3: 上下俯仰 (1500-2500, 中点2047)  
// ID 4: 末端 (1800-2300, 中点2047)

// ---- 普通微动参数 ----
#define NECK_MOVE_INTERVAL_MIN    1200   // 微动间隔最短 1.2 秒
#define NECK_MOVE_INTERVAL_MAX    3000   // 微动间隔最长 3 秒
#define NECK_MOVE_DURATION        800    // 微动持续时间 800ms（更平滑）

// 脖子1号舵机（左右旋转）
#define NECK1_MOVE_AMP            150    // 普通左右微动幅度
#define NECK1_BIG_MOVE_AMP        400    // ★ 大幅度左右转动
#define NECK1_BIG_MOVE_PROB       0.20f  // ★ 20%概率大幅度转动
#define NECK1_BIG_MOVE_DURATION   1200   // 大幅度转动持续时间更长

// 脖子2、3号舵机（俯仰）- 动作幅度更大
#define NECK23_MOVE_AMP           120    // ★ 俯仰微动幅度加大 (±120)
#define NECK23_MOVE_DURATION      900    // 俯仰动作持续时间

// 脖子4号舵机 - 摇头晃脑
#define NECK4_MOVE_AMP            40     // 普通微动幅度
#define NECK4_SHAKE_PROB          0.25f  // ★ 25%概率摇头晃脑
#define NECK4_SHAKE_COUNT_MIN     2      // 摇头次数最少
#define NECK4_SHAKE_COUNT_MAX     4      // 摇头次数最多
#define NECK4_SHAKE_AMP           60     // 摇头幅度
#define NECK4_SHAKE_DURATION      200    // 单次摇头持续时间

// ==================== 情绪类型 ====================
enum EmotionType {
  EMO_IDLE = 0,
  EMO_ANGRY,
  EMO_SAD,
  EMO_HAPPY,
  EMO_SPEECHLESS,
  EMO_WINK,
  EMO_NORMAL,
  EMO_TEST,      // 测试表情：用于测试所有舵机
  EMO_COUNT
};

// ==================== 眼球移动状态（极简版）====================
enum EyeMoveState {
  EYE_IDLE,            // 空闲/等待
  EYE_MICRO_MOVE,      // 微动中（半秒一次）
  EYE_BIG_MOVE         // 大动中（几秒一次）
};

// ==================== 动画状态 ====================
struct FaceAnimState {
  EmotionType currentEmotion;
  
  // 舵机角度（直接值，不用平滑）
  int eyeUD;
  int eyeLR;
  int eyelidL;
  int eyelidR;
  int lidRotL;
  int lidRotR;
  int mouth;
  int wingA;      // 翅膀A
  int wingB;      // 翅膀B
  int butt;       // 屁股
  
  // 时间控制
  uint32_t lastUpdateMs;
  uint32_t blinkNextMs;
  uint32_t mouthCuteNextMs;
  uint32_t bodyActionNextMs;  // 身体动作计时器
  
  // 眨眼
  bool isBlinking;
  uint8_t blinkPhase;
  uint32_t blinkStartMs;
  
  // 嘴巴卖萌
  bool isMouthCute;
  uint8_t mouthCuteType;
  uint8_t mouthCuteStep;
  uint8_t mouthCuteCount;
  int mouthCuteTarget;
  uint32_t mouthCuteStartMs;
  uint32_t mouthCuteDuration;
  
  // 眼球移动（关键：基于时间的精确插值）
  EyeMoveState eyeState;
  int eyeStartUD, eyeStartLR;      // 移动起点
  int eyeEndUD, eyeEndLR;          // 移动终点
  int eyeBaseUD, eyeBaseLR;        // 微动基准点
  uint32_t eyeMoveStartMs;         // 移动开始时间
  uint32_t eyeMoveDuration;        // 移动持续时间
  uint32_t eyePhaseEndMs;          // 当前阶段结束时间
  uint8_t eyeSweepCycles;          // 扫视剩余次数
  int8_t eyeSweepSide;             // 扫视方向
  
  // 眼皮微动
  int eyelidJitterL, eyelidJitterR;
  uint32_t eyelidJitterNextMs;
  
  // 音频嘴巴
  bool audioMouthActive;
  float audioMouthLevel;
  
  // 情绪动画
  uint8_t emotionStep;
  uint32_t emotionStepMs;
  uint32_t emotionEndMs;
  int emotionStartRotL, emotionStartRotR;
  int8_t emotionSide;
  uint8_t emotionCount;
  
  // ★ 表情嘴部舵机（4通道）
  // 这些值只在表情动画期间控制，说话时由 taskMouthDriver 接管
  int mouthR;       // CH0 右嘴角 (70-90)
  int mouthL;       // CH1 左嘴角 (90-110)
  int mouthU;       // CH2 上嘴唇 (65-110)
  int mouthLower;   // CH3 下嘴唇 (45-90)
  bool exprMouthActive;  // 表情嘴部动画是否激活
  
  // ★ 脖子舵机微动状态（SCServo ID 1-4）
  uint32_t neckMoveNextMs;    // 下次脖子微动时间
  bool neckMoving;            // 是否正在微动
  uint32_t neckMoveStartMs;   // 微动开始时间
  uint32_t neckMoveDuration;  // 当前微动持续时间（可变）
  
  // 1号舵机（左右旋转）
  int neck1Start, neck1End;   // 起止位置
  int neck1Current;           // 当前位置
  bool neck1BigMove;          // 是否大幅度移动
  
  // 2、3号舵机（俯仰）
  int neck23Start, neck23End; // 起止位置
  int neck23Current;          // 当前位置
  
  // 4号舵机（摇头晃脑）
  int neck4Start, neck4End;   // 起止位置
  int neck4Current;           // 当前位置
  bool neck4Shaking;          // 是否正在摇头晃脑
  uint8_t neck4ShakeCount;    // 剩余摇头次数
  uint8_t neck4ShakePhase;    // 摇头阶段（0=向左，1=向右）
  uint32_t neck4ShakeStartMs; // 当前摇头开始时间
};

FaceAnimState faceAnim;

// ==================== 动画启用控制 ====================
bool faceAnimEnabled = false;         // 只有连接成功后才启用动画
uint32_t lastResetCheckMs = 0;        // 上次归位检查时间
#define RESET_CHECK_INTERVAL_MS 30000 // 30秒一次归位检查点

// ==================== 眼球移动计时器 ====================
uint32_t eyeMicroNextMs = 0;          // 下次微动时间
uint32_t eyeBigNextMs = 0;            // 下次大动时间

// ==================== 人脸追踪状态 ====================
bool faceTrackingActive = false;      // 是否正在追踪人脸
int faceTrackTargetLR = 85;           // 人脸追踪目标左右角度
int faceTrackTargetUD = 90;           // 人脸追踪目标上下角度
float faceTrackCurrentLR = 85;        // 人脸追踪当前左右角度（平滑用）
float faceTrackCurrentUD = 90;        // 人脸追踪当前上下角度（平滑用）
uint32_t faceTrackLastUpdateMs = 0;   // 上次收到追踪命令的时间
#define FACE_TRACK_TIMEOUT_MS 800     // 追踪命令超时时间（毫秒）
#define FACE_TRACK_SMOOTH 0.75f       // 眼球追踪平滑系数（越大越快到位，减少步数）

// 前向声明（函数在文件后面定义）
void faceAnimStopEyeTrack();
void faceAnimSetEyeTrack(int lr, int ud);

// 眼皮遥控控制（手部遮挡动画）- 前向声明
extern bool eyelidRemoteControl;
void updateEyelidRemote(uint32_t now);
void faceAnimEyelidBlinkFast();
void faceAnimEyelidCloseBoth();

// 嘴型控制 - 前向声明
void updateMouthShape();
void setMouthShape(char vowel, float volume);
void resetMouthShape();
void faceAnimEyelidPeek(bool leftEye);
void faceAnimEyelidNormal();

// ==================== 呼吸感状态（身体动作）====================
uint32_t breathCycleMs = 3000;        // 当前呼吸周期
uint32_t breathStartMs = 0;           // 当前呼吸开始时间
float breathPhaseOffset = 0;          // 呼吸相位偏移（让翅膀和屁股错开）
uint32_t nextBigActionMs = 0;         // 下次大动作时间
uint32_t breathPauseEndMs = 0;        // 暂停结束时间

extern void setServoAngle(uint8_t ch, int angle);

// 脖子微动更新函数（前向声明）
void updateNeckMove(uint32_t now);

// ★ 脖子舵机控制命令队列（避免每帧发送，只在动作开始时发送一次）
struct NeckServoCmd {
  int id;           // 舵机ID (1-4)
  int targetPos;    // 目标位置
  int speed;        // 速度
  int acc;          // 加速度
  bool pending;     // 是否待发送
};
NeckServoCmd neckCmds[5] = {{0,0,0,0,false}, {1,2025,0,0,false}, {2,2047,0,0,false}, {3,2047,0,0,false}, {4,2047,0,0,false}};

// 设置脖子舵机命令（只标记，不立即发送）
void setNeckServoCmd(int id, int pos, int speed, int acc) {
  if (id < 1 || id > 4) return;
  neckCmds[id].targetPos = pos;
  neckCmds[id].speed = speed;
  neckCmds[id].acc = acc;
  neckCmds[id].pending = true;
}

// ==================== 辅助函数 ====================
inline int randInt(int minV, int maxV) {
  if (maxV <= minV) return minV;
  return minV + random(maxV - minV + 1);
}

inline float randFloat(float minV, float maxV) {
  return minV + (float)random(10001) / 10000.0f * (maxV - minV);
}

inline int clampInt(int v, int minV, int maxV) {
  if (v < minV) return minV;
  if (v > maxV) return maxV;
  return v;
}

// 右眼皮是"反向"的：大数字=闭合，小数字=张开
// 所以 EYELID_R_CLOSED=130 > EYELID_R_MAX_OPEN=50
inline int clampEyelidR(int v) {
  if (v > EYELID_R_CLOSED) return EYELID_R_CLOSED;
  if (v < EYELID_R_MAX_OPEN) return EYELID_R_MAX_OPEN;
  return v;
}

inline int clampEyelidL(int v) {
  if (v < EYELID_L_CLOSED) return EYELID_L_CLOSED;
  if (v > EYELID_L_MAX_OPEN) return EYELID_L_MAX_OPEN;
  return v;
}

inline float easeInOut(float t) {
  return t * t * (3.0f - 2.0f * t);
}

inline float easeOut(float t) {
  return t * (2.0f - t);  // 开始快，结束慢
}

inline float easeIn(float t) {
  return t * t;  // 开始慢，结束快
}

// 贝塞尔曲线缓动（更平滑，适合呼吸感）
// cubic-bezier(0.4, 0, 0.2, 1) - Material Design 标准缓动
inline float easeBezier(float t) {
  // 三次贝塞尔近似：开始慢，中间快，结束慢
  float t2 = t * t;
  float t3 = t2 * t;
  return 3.0f * t2 - 2.0f * t3;  // smoothstep
}

// ==================== 眼球移动专用曲线 ====================
// 先快-中间匀速-后快 的贝塞尔曲线
// 0-30%: 快速启动（ease-out效果）
// 30-70%: 匀速移动
// 70-100%: 快速到达（ease-in效果）
inline float easeEyeMove(float t) {
  if (t < 0.3f) {
    // 前30%：快速启动 (ease-out)
    float localT = t / 0.3f;
    return 0.3f * (1.0f - (1.0f - localT) * (1.0f - localT));
  } else if (t < 0.7f) {
    // 中间40%：匀速移动
    float localT = (t - 0.3f) / 0.4f;
    return 0.3f + 0.4f * localT;
  } else {
    // 后30%：快速到达 (ease-in)
    float localT = (t - 0.7f) / 0.3f;
    return 0.7f + 0.3f * localT * localT;
  }
}

// ==================== 眨眼专用曲线 ====================
// 闭眼阶段：开始慢，结束快（眼皮碰到时最快）
inline float easeBlinkClose(float t) {
  // 三次方：开始慢，结束快
  return t * t * t;
}

// 睁眼阶段：开始快，结束慢（刚睁开时最快）
inline float easeBlinkOpen(float t) {
  // 反向三次方：开始快，结束慢
  float inv = 1.0f - t;
  return 1.0f - inv * inv * inv;
}

// 呼吸感缓动（正弦波，非常平滑）
inline float easeBreath(float t) {
  // 使用正弦波，0->1->0 的平滑过渡
  return (1.0f - cosf(t * 3.14159f)) * 0.5f;
}

// 弹性缓动（用于俏皮的动作）
inline float easeElasticOut(float t) {
  if (t <= 0) return 0;
  if (t >= 1) return 1;
  return powf(2, -10 * t) * sinf((t - 0.1f) * 5 * 3.14159f) + 1;
}

const char* EMOTION_NAMES[] = {
  "idle", "angry", "sad", "happy", "speechless", "wink", "normal", "test"
};

// ==================== 计算眼皮基础角度 ====================
void computeEyelidBase(int curUD, int& baseL, int& baseR) {
  float rangeUD = EYE_UD_MAX - EYE_UD_MIN;
  float ratio = (float)(curUD - EYE_UD_MIN) / rangeUD;
  
  if (ratio >= EYELID_LOOKUP_THRESHOLD) {
    baseL = EYELID_L_MAX_OPEN;
    baseR = EYELID_R_MAX_OPEN;
  } else if (ratio <= EYELID_LOOKDOWN_THRESHOLD) {
    baseL = (EYELID_L_NORMAL + EYELID_L_CLOSED) / 2;
    baseR = (EYELID_R_NORMAL + EYELID_R_CLOSED) / 2;
  } else {
    baseL = EYELID_L_NORMAL;
    baseR = EYELID_R_NORMAL;
  }
}

// ==================== 应用舵机角度 ====================
// 外部优先控制标志（最高优先级，供树莓派使用）
bool externalServoOverride[16] = {false};  // 每个通道的外部控制标志
int externalServoAngles[16] = {90};        // 外部控制的角度值
uint32_t externalServoTimeout[16] = {0};   // 外部控制超时时间（自动释放）

void applyServos() {
  // 翅膀和屁股（检查外部优先控制）
  if (!externalServoOverride[CH_WING_A]) {
    setServoAngle(CH_WING_A, faceAnim.wingA);
  }
  if (!externalServoOverride[CH_WING_B]) {
    setServoAngle(CH_WING_B, faceAnim.wingB);
  }
  if (!externalServoOverride[CH_BUTT]) {
    setServoAngle(CH_BUTT, faceAnim.butt);
  }
  
  // 眼睛
  if (!externalServoOverride[CH_EYE_UD]) {
    setServoAngle(CH_EYE_UD, faceAnim.eyeUD);
  }
  if (!externalServoOverride[CH_EYE_LR_L]) {
    setServoAngle(CH_EYE_LR_L, faceAnim.eyeLR);
  }
  if (!externalServoOverride[CH_EYE_LR_R]) {
    setServoAngle(CH_EYE_LR_R, faceAnim.eyeLR);
  }
  
  // 眼皮
  if (!externalServoOverride[CH_EYELID_L]) {
    setServoAngle(CH_EYELID_L, faceAnim.eyelidL);
  }
  if (!externalServoOverride[CH_EYELID_R]) {
    setServoAngle(CH_EYELID_R, faceAnim.eyelidR);
  }
  if (!externalServoOverride[CH_LID_ROT_L]) {
    setServoAngle(CH_LID_ROT_L, faceAnim.lidRotL);
  }
  if (!externalServoOverride[CH_LID_ROT_R]) {
    setServoAngle(CH_LID_ROT_R, faceAnim.lidRotR);
  }
  
  // 嘴巴（旧通道 CH9，保留兼容）
  if (!externalServoOverride[CH_MOUTH]) {
    if (!faceAnim.audioMouthActive) {
      setServoAngle(CH_MOUTH, faceAnim.mouth);
    } else {
      int mouthAngle = MOUTH_CLOSED + (int)((MOUTH_MAX_OPEN - MOUTH_CLOSED) * faceAnim.audioMouthLevel);
      setServoAngle(CH_MOUTH, mouthAngle);
    }
  }
  
  // ★ 4通道嘴部舵机（CH0-CH3）完全由 taskMouthDriver 控制
  // 这里不再控制，避免和 taskMouthDriver 冲突
  // taskMouthDriver 会根据 faceAnim.exprMouthActive 和音频状态来决定目标值
}

// 外部舵机控制接口（最高优先级）
void setExternalServoControl(uint8_t ch, int angle, uint32_t durationMs) {
  if (ch >= 16) return;
  externalServoOverride[ch] = true;
  externalServoAngles[ch] = angle;
  externalServoTimeout[ch] = millis() + durationMs;
  setServoAngle(ch, angle);  // 立即生效
  Serial.printf("[SERVO] External control: ch=%d angle=%d duration=%dms\n", ch, angle, durationMs);
}

// 释放外部控制
void releaseExternalServoControl(uint8_t ch) {
  if (ch >= 16) return;
  externalServoOverride[ch] = false;
}

// 检查并释放超时的外部控制
void checkExternalServoTimeout() {
  uint32_t now = millis();
  for (int i = 0; i < 16; i++) {
    if (externalServoOverride[i] && now >= externalServoTimeout[i]) {
      externalServoOverride[i] = false;
    }
  }
}

// ==================== 初始化 ====================
void faceAnimInit() {
  memset(&faceAnim, 0, sizeof(faceAnim));
  
  faceAnim.currentEmotion = EMO_IDLE;
  
  faceAnim.eyeUD = 90;
  faceAnim.eyeLR = 90;
  faceAnim.eyelidL = EYELID_L_NORMAL;
  faceAnim.eyelidR = EYELID_R_NORMAL;
  faceAnim.lidRotL = LID_ROT_L_NORMAL;
  faceAnim.lidRotR = LID_ROT_R_NORMAL;
  faceAnim.mouth = MOUTH_CLOSED;
  
  // 翅膀和屁股初始化为中立位
  faceAnim.wingA = WING_A_NEUTRAL;
  faceAnim.wingB = WING_B_NEUTRAL;
  faceAnim.butt = BUTT_NEUTRAL;
  
  // ★ 嘴部舵机初始化为中立位
  faceAnim.mouthR = MOUTH_R_NEUTRAL;
  faceAnim.mouthL = MOUTH_L_NEUTRAL;
  faceAnim.mouthU = MOUTH_U_NEUTRAL;
  faceAnim.mouthLower = MOUTH_LOWER_CLOSED;
  faceAnim.exprMouthActive = false;
  
  // 初始化眼皮 jitter 为 0（不偏移）
  faceAnim.eyelidJitterL = 0;
  faceAnim.eyelidJitterR = 0;
  
  uint32_t now = millis();
  faceAnim.lastUpdateMs = now;
  faceAnim.blinkNextMs = now + randInt(BLINK_INTERVAL_MIN_MS, BLINK_INTERVAL_MAX_MS);
  faceAnim.mouthCuteNextMs = now + randInt(MOUTH_CUTE_INTERVAL_MIN, MOUTH_CUTE_INTERVAL_MAX);
  faceAnim.eyelidJitterNextMs = now + randInt(EYELID_JITTER_INTERVAL_MIN, EYELID_JITTER_INTERVAL_MAX);
  faceAnim.bodyActionNextMs = now + randInt(BIG_ACTION_INTERVAL_MIN, BIG_ACTION_INTERVAL_MAX);
  
  faceAnim.eyeState = EYE_IDLE;
  faceAnim.eyeBaseUD = 90;
  faceAnim.eyeBaseLR = 90;
  
  // 初始化眼球移动计时器
  eyeMicroNextMs = now + randInt(EYE_MICRO_INTERVAL_MIN, EYE_MICRO_INTERVAL_MAX);
  eyeBigNextMs = now + randInt(EYE_BIG_MOVE_INTERVAL_MIN, EYE_BIG_MOVE_INTERVAL_MAX);
  
  // 初始化呼吸感状态
  breathCycleMs = randInt(BREATH_CYCLE_MIN, BREATH_CYCLE_MAX);
  breathStartMs = now;
  breathPhaseOffset = randFloat(0, 0.3f);
  nextBigActionMs = now + randInt(BIG_ACTION_INTERVAL_MIN, BIG_ACTION_INTERVAL_MAX);
  breathPauseEndMs = 0;
  
  // ★ 初始化脖子微动状态
  faceAnim.neckMoveNextMs = now + randInt(NECK_MOVE_INTERVAL_MIN, NECK_MOVE_INTERVAL_MAX);
  faceAnim.neckMoving = false;
  faceAnim.neckMoveDuration = NECK_MOVE_DURATION;
  faceAnim.neck1Current = 2025;   // 1号舵机中位
  faceAnim.neck1BigMove = false;
  faceAnim.neck23Current = 2047;  // 2、3号舵机中位
  faceAnim.neck4Current = 2047;   // 4号舵机中位
  faceAnim.neck4Shaking = false;
  faceAnim.neck4ShakeCount = 0;
  faceAnim.neck4ShakePhase = 0;
  
  Serial.printf("[FACE] Animation init (speed=%.1fx)\n", ANIM_SPEED_MULTIPLIER);
}

// ==================== Idle: 眨眼（使用贝塞尔曲线：闭眼加速，睁眼减速）====================
// 闭眼阶段：开始慢-结束快（眼皮碰到时最快）
// 睁眼阶段：开始快-结束慢（刚睁开时最快）
void updateIdleBlink(uint32_t now) {
  if (!faceAnim.isBlinking) {
    // 检查是否到眨眼时间
    if (now >= faceAnim.blinkNextMs) {
      faceAnim.isBlinking = true;
      faceAnim.blinkPhase = 1;
      faceAnim.blinkStartMs = now;
      // Serial.println("[BLINK] Start closing");
    }
    return;
  }
  
  uint32_t elapsed = now - faceAnim.blinkStartMs;
  
  if (faceAnim.blinkPhase == 1) {
    // 闭眼阶段：使用 easeBlinkClose（开始慢，结束快）
    if (elapsed < BLINK_CLOSE_DURATION_MS) {
      float t = easeBlinkClose((float)elapsed / BLINK_CLOSE_DURATION_MS);
      // 左眼皮：从正常位置(110)到闭合位置(50)
      faceAnim.eyelidL = EYELID_L_NORMAL + (int)((EYELID_L_CLOSED - EYELID_L_NORMAL) * t);
      // 右眼皮：从正常位置(70)到闭合位置(130)（反向）
      faceAnim.eyelidR = EYELID_R_NORMAL + (int)((EYELID_R_CLOSED - EYELID_R_NORMAL) * t);
    } else {
      // 闭眼完成
      faceAnim.eyelidL = EYELID_L_CLOSED;
      faceAnim.eyelidR = EYELID_R_CLOSED;
      faceAnim.blinkPhase = 2;
      faceAnim.blinkStartMs = now;
      // Serial.println("[BLINK] Start opening");
    }
  } else if (faceAnim.blinkPhase == 2) {
    // 睁眼阶段：使用 easeBlinkOpen（开始快，结束慢）
    if (elapsed < BLINK_OPEN_DURATION_MS) {
      float t = easeBlinkOpen((float)elapsed / BLINK_OPEN_DURATION_MS);
      // 左眼皮：从闭合位置(50)到最大张开(130)
      faceAnim.eyelidL = EYELID_L_CLOSED + (int)((EYELID_L_MAX_OPEN - EYELID_L_CLOSED) * t);
      // 右眼皮：从闭合位置(130)到最大张开(50)（反向）
      faceAnim.eyelidR = EYELID_R_CLOSED + (int)((EYELID_R_MAX_OPEN - EYELID_R_CLOSED) * t);
    } else {
      // 睁眼完成
      faceAnim.eyelidL = EYELID_L_MAX_OPEN;
      faceAnim.eyelidR = EYELID_R_MAX_OPEN;
      faceAnim.isBlinking = false;
      faceAnim.blinkPhase = 0;
      faceAnim.blinkNextMs = now + randInt(BLINK_INTERVAL_MIN_MS, BLINK_INTERVAL_MAX_MS);
      
      // 眨眼后触发嘴巴卖萌
      if (randFloat(0, 1) < MOUTH_CUTE_BLINK_PROB && !faceAnim.isMouthCute && !faceAnim.audioMouthActive) {
        faceAnim.mouthCuteNextMs = now;
      }
      // Serial.println("[BLINK] Complete");
    }
  }
}

// ==================== Idle: 嘴巴卖萌 ====================
void updateIdleMouthCute(uint32_t now) {
  if (faceAnim.audioMouthActive) return;
  
  if (!faceAnim.isMouthCute) {
    if (now >= faceAnim.mouthCuteNextMs) {
      faceAnim.isMouthCute = true;
      faceAnim.mouthCuteType = random(2);
      faceAnim.mouthCuteStep = 0;
      faceAnim.mouthCuteStartMs = now;
      
      int range = MOUTH_MAX_OPEN - MOUTH_CLOSED;
      // Serial.printf("[MOUTH] Cute started! type=%d, range=%d\n", faceAnim.mouthCuteType, range);
      if (faceAnim.mouthCuteType == 0) {
        faceAnim.mouthCuteTarget = MOUTH_CLOSED + (int)(range * randFloat(MOUTH_SLOW_AMOUNT_MIN, MOUTH_SLOW_AMOUNT_MAX));
        faceAnim.mouthCuteDuration = randInt(MOUTH_SLOW_OPEN_MIN, MOUTH_SLOW_OPEN_MAX);
      } else {
        faceAnim.mouthCuteTarget = MOUTH_CLOSED + (int)(range * randFloat(MOUTH_FLAP_AMOUNT_MIN, MOUTH_FLAP_AMOUNT_MAX));
        faceAnim.mouthCuteCount = randInt(MOUTH_FLAP_COUNT_MIN, MOUTH_FLAP_COUNT_MAX);
        faceAnim.mouthCuteDuration = MOUTH_FLAP_DURATION;
      }
    }
    return;
  }
  
  uint32_t elapsed = now - faceAnim.mouthCuteStartMs;
  
  if (faceAnim.mouthCuteType == 0) {
    // 慢开快合
    if (faceAnim.mouthCuteStep == 0) {
      // 慢慢张开
      if (elapsed < faceAnim.mouthCuteDuration) {
        float t = easeOut((float)elapsed / faceAnim.mouthCuteDuration);
        faceAnim.mouth = MOUTH_CLOSED + (int)((faceAnim.mouthCuteTarget - MOUTH_CLOSED) * t);
      } else {
        faceAnim.mouthCuteStep = 1;
        faceAnim.mouthCuteStartMs = now;
        faceAnim.mouthCuteDuration = randInt(MOUTH_HOLD_OPEN_MIN, MOUTH_HOLD_OPEN_MAX);
      }
    } else if (faceAnim.mouthCuteStep == 1) {
      // 保持
      if (elapsed >= faceAnim.mouthCuteDuration) {
        faceAnim.mouthCuteStep = 2;
        faceAnim.mouthCuteStartMs = now;
      }
    } else {
      // 快速合上
      if (elapsed < MOUTH_FAST_CLOSE) {
        float t = (float)elapsed / MOUTH_FAST_CLOSE;
        faceAnim.mouth = faceAnim.mouthCuteTarget + (int)((MOUTH_CLOSED - faceAnim.mouthCuteTarget) * t);
      } else {
        faceAnim.mouth = MOUTH_CLOSED;
        faceAnim.isMouthCute = false;
        faceAnim.mouthCuteNextMs = now + randInt(MOUTH_CUTE_INTERVAL_MIN, MOUTH_CUTE_INTERVAL_MAX);
      }
    }
  } else {
    // 开合n次
    uint8_t curCycle = faceAnim.mouthCuteStep / 2;
    bool opening = (faceAnim.mouthCuteStep % 2 == 0);
    
    if (curCycle < faceAnim.mouthCuteCount) {
      if (elapsed < MOUTH_FLAP_DURATION) {
        float t = (float)elapsed / MOUTH_FLAP_DURATION;
        if (opening) {
          faceAnim.mouth = MOUTH_CLOSED + (int)((faceAnim.mouthCuteTarget - MOUTH_CLOSED) * t);
        } else {
          faceAnim.mouth = faceAnim.mouthCuteTarget + (int)((MOUTH_CLOSED - faceAnim.mouthCuteTarget) * t);
        }
      } else {
        faceAnim.mouthCuteStep++;
        faceAnim.mouthCuteStartMs = now;
      }
    } else {
      faceAnim.mouth = MOUTH_CLOSED;
      faceAnim.isMouthCute = false;
      faceAnim.mouthCuteNextMs = now + randInt(MOUTH_CUTE_INTERVAL_MIN, MOUTH_CUTE_INTERVAL_MAX);
    }
  }
}

// ==================== Idle: 眼球移动（极简版：微动+大动）====================
// 设计：半秒微动一次，几秒大动一次，都是随机位置
// 注意：eyeMicroNextMs 和 eyeBigNextMs 已在前面声明

void updateIdleEyeMove(uint32_t now) {
  // ========== 人脸追踪模式（最高优先级）==========
  if (faceTrackingActive) {
    // 检查超时
    if (now - faceTrackLastUpdateMs > FACE_TRACK_TIMEOUT_MS) {
      faceAnimStopEyeTrack();
    } else {
      // 平滑插值到目标位置
      faceTrackCurrentLR += (faceTrackTargetLR - faceTrackCurrentLR) * FACE_TRACK_SMOOTH;
      faceTrackCurrentUD += (faceTrackTargetUD - faceTrackCurrentUD) * FACE_TRACK_SMOOTH;
      
      // 应用到眼球（限制在安全范围）
      faceAnim.eyeLR = clampInt((int)faceTrackCurrentLR, EYE_LR_MIN, EYE_LR_MAX);
      faceAnim.eyeUD = clampInt((int)faceTrackCurrentUD, EYE_UD_MIN, EYE_UD_MAX);
      
      // 跳过随机眼球运动，但仍然更新眼皮
      goto update_eyelids;
    }
  }
  
  // ========== 大动逻辑（优先级高）==========
  if (faceAnim.eyeState == EYE_BIG_MOVE) {
    // 正在大动，执行插值（使用眼球专用曲线：先快-中间匀速-后快）
    uint32_t elapsed = now - faceAnim.eyeMoveStartMs;
    if (elapsed < faceAnim.eyeMoveDuration) {
      float t = easeEyeMove((float)elapsed / faceAnim.eyeMoveDuration);
      faceAnim.eyeUD = faceAnim.eyeStartUD + (int)((faceAnim.eyeEndUD - faceAnim.eyeStartUD) * t);
      faceAnim.eyeLR = faceAnim.eyeStartLR + (int)((faceAnim.eyeEndLR - faceAnim.eyeStartLR) * t);
    } else {
      // 大动完成
      faceAnim.eyeUD = faceAnim.eyeEndUD;
      faceAnim.eyeLR = faceAnim.eyeEndLR;
      faceAnim.eyeBaseUD = faceAnim.eyeUD;
      faceAnim.eyeBaseLR = faceAnim.eyeLR;
      faceAnim.eyeState = EYE_IDLE;
      
      // 大动后可能触发嘴巴卖萌
      if (randFloat(0, 1) < MOUTH_CUTE_PROB && !faceAnim.isMouthCute && !faceAnim.audioMouthActive) {
        faceAnim.mouthCuteNextMs = now;
      }
    }
  }
  // ========== 微动逻辑 ==========
  else if (faceAnim.eyeState == EYE_MICRO_MOVE) {
    // 正在微动，执行插值（使用眼球专用曲线：先快-中间匀速-后快）
    uint32_t elapsed = now - faceAnim.eyeMoveStartMs;
    if (elapsed < EYE_MICRO_MOVE_TIME) {
      float t = easeEyeMove((float)elapsed / EYE_MICRO_MOVE_TIME);
      faceAnim.eyeUD = faceAnim.eyeStartUD + (int)((faceAnim.eyeEndUD - faceAnim.eyeStartUD) * t);
      faceAnim.eyeLR = faceAnim.eyeStartLR + (int)((faceAnim.eyeEndLR - faceAnim.eyeStartLR) * t);
    } else {
      // 微动完成
      faceAnim.eyeUD = faceAnim.eyeEndUD;
      faceAnim.eyeLR = faceAnim.eyeEndLR;
      faceAnim.eyeState = EYE_IDLE;
    }
  }
  // ========== 空闲状态：检查是否该开始新动作 ==========
  else {
    // 检查是否该大动了（优先级高）
    if (now >= eyeBigNextMs) {
      // 开始大动
      faceAnim.eyeStartUD = faceAnim.eyeUD;
      faceAnim.eyeStartLR = faceAnim.eyeLR;
      
      int udOffset, lrOffset;
      
      // 判断是否执行斜向移动
      if (randFloat(0, 1) < EYE_DIAGONAL_PROB) {
        // ========== 斜向移动：水平+垂直同时大幅变化 ==========
        // 随机选择四个对角方向之一：左上(0)、右上(1)、左下(2)、右下(3)
        int direction = randInt(0, 4);  // 0-3
        
        switch (direction) {
          case 0:  // 左上
            udOffset = randInt(15, EYE_DIAGONAL_AMP_UD);   // 往上
            lrOffset = -randInt(20, EYE_DIAGONAL_AMP_LR);  // 往左
            break;
          case 1:  // 右上
            udOffset = randInt(15, EYE_DIAGONAL_AMP_UD);   // 往上
            lrOffset = randInt(20, EYE_DIAGONAL_AMP_LR);   // 往右
            break;
          case 2:  // 左下
            udOffset = -randInt(10, EYE_DIAGONAL_AMP_UD / 2);  // 往下（幅度小）
            lrOffset = -randInt(20, EYE_DIAGONAL_AMP_LR);  // 往左
            break;
          default: // 右下
            udOffset = -randInt(10, EYE_DIAGONAL_AMP_UD / 2);  // 往下（幅度小）
            lrOffset = randInt(20, EYE_DIAGONAL_AMP_LR);   // 往右
            break;
        }
        // Serial.printf("[EYE] Diagonal move dir=%d\n", direction);
      } else {
        // ========== 普通大动：随机位置 ==========
        // 根据 EYE_UP_BIAS 决定往上/往下的概率
        if (randFloat(0, 1) < EYE_UP_BIAS) {
          // 往上看（正值 = 往上）
          udOffset = randInt(5, EYE_BIG_AMP_UD);
        } else {
          // 往下看（负值 = 往下，幅度小一点）
          udOffset = -randInt(5, EYE_BIG_AMP_UD / 2);
        }
        lrOffset = randInt(-EYE_BIG_AMP_LR, EYE_BIG_AMP_LR);
      }
      
      faceAnim.eyeEndUD = EYE_CENTER_UD + udOffset;
      faceAnim.eyeEndLR = EYE_CENTER_LR + lrOffset;
      faceAnim.eyeEndUD = clampInt(faceAnim.eyeEndUD, EYE_UD_MIN, EYE_UD_MAX);
      faceAnim.eyeEndLR = clampInt(faceAnim.eyeEndLR, EYE_LR_MIN, EYE_LR_MAX);
      
      faceAnim.eyeMoveStartMs = now;
      faceAnim.eyeMoveDuration = randInt(EYE_BIG_MOVE_TIME_MIN, EYE_BIG_MOVE_TIME_MAX);
      faceAnim.eyeState = EYE_BIG_MOVE;
      
      // 设置下次大动时间
      eyeBigNextMs = now + randInt(EYE_BIG_MOVE_INTERVAL_MIN, EYE_BIG_MOVE_INTERVAL_MAX);
      
      // Serial.printf("[EYE] Big move to UD=%d, LR=%d\n", faceAnim.eyeEndUD, faceAnim.eyeEndLR);
    }
    // 检查是否该微动了
    else if (now >= eyeMicroNextMs) {
      // 开始微动
      faceAnim.eyeStartUD = faceAnim.eyeUD;
      faceAnim.eyeStartLR = faceAnim.eyeLR;
      
      // 在当前位置附近小幅移动（偏向往上）
      int microUdOffset;
      if (randFloat(0, 1) < EYE_UP_BIAS) {
        // 往上微动
        microUdOffset = randInt(0, EYE_MICRO_AMP_UD);
      } else {
        // 往下微动（幅度小一点）
        microUdOffset = -randInt(0, EYE_MICRO_AMP_UD / 2);
      }
      faceAnim.eyeEndUD = faceAnim.eyeUD + microUdOffset;
      faceAnim.eyeEndLR = faceAnim.eyeLR + randInt(-EYE_MICRO_AMP_LR, EYE_MICRO_AMP_LR);
      faceAnim.eyeEndUD = clampInt(faceAnim.eyeEndUD, EYE_UD_MIN, EYE_UD_MAX);
      faceAnim.eyeEndLR = clampInt(faceAnim.eyeEndLR, EYE_LR_MIN, EYE_LR_MAX);
      
      faceAnim.eyeMoveStartMs = now;
      faceAnim.eyeState = EYE_MICRO_MOVE;
      
      // 设置下次微动时间
      eyeMicroNextMs = now + randInt(EYE_MICRO_INTERVAL_MIN, EYE_MICRO_INTERVAL_MAX);
    }
  }
  
update_eyelids:
  // ========== 更新眼皮（非眨眼时）==========
  if (!faceAnim.isBlinking) {
    // 眼皮微动
    if (now >= faceAnim.eyelidJitterNextMs) {
      faceAnim.eyelidJitterL = randInt(EYELID_JITTER_MIN, EYELID_JITTER_MAX);
      faceAnim.eyelidJitterR = -randInt(EYELID_JITTER_MIN, EYELID_JITTER_MAX);
      faceAnim.eyelidJitterNextMs = now + randInt(EYELID_JITTER_INTERVAL_MIN, EYELID_JITTER_INTERVAL_MAX);
    }
    
    int baseL, baseR;
    computeEyelidBase(faceAnim.eyeUD, baseL, baseR);
    faceAnim.eyelidL = clampEyelidL(baseL + faceAnim.eyelidJitterL);
    faceAnim.eyelidR = clampEyelidR(baseR + faceAnim.eyelidJitterR);
  }
}

// ==================== Idle: 身体动作（翅膀扑腾、屁股扭动）====================
// 身体动作状态
// ==================== 身体动作状态（呼吸感 + 偶尔大动作）====================
enum BodyActionState {
  BODY_BREATHING = 0,  // 呼吸微动（默认）
  BODY_PAUSED,         // 暂停（偶尔停一会）
  BODY_WING_FLAP,      // 翅膀扑腾（大动作）
  BODY_BUTT_WIGGLE     // 屁股翘起（大动作）
};

BodyActionState bodyState = BODY_BREATHING;
uint8_t bodyActionCount = 0;
uint8_t bodyActionStep = 0;
uint32_t bodyActionStartMs = 0;

// 呼吸感状态变量已在前面声明

// 限制翅膀角度不超过下限
inline int clampWingA(int v) {
  if (v > WING_A_LOW) return WING_A_LOW;   // 不超过120
  if (v < WING_A_HIGH) return WING_A_HIGH; // 不低于40
  return v;
}

inline int clampWingB(int v) {
  if (v < WING_B_LOW) return WING_B_LOW;   // 不低于60
  if (v > WING_B_HIGH) return WING_B_HIGH; // 不超过140
  return v;
}

inline int clampButt(int v) {
  if (v > BUTT_LOW) return BUTT_LOW;       // 不超过90
  if (v < BUTT_HIGH) return BUTT_HIGH;     // 不低于40
  return v;
}

void initBodyBreathing(uint32_t now) {
  breathCycleMs = randInt(BREATH_CYCLE_MIN, BREATH_CYCLE_MAX);
  breathStartMs = now;
  breathPhaseOffset = randFloat(0, 0.3f);  // 随机相位偏移
  bodyState = BODY_BREATHING;
}

void updateIdleBodyAction(uint32_t now) {
  // ========== 检查是否触发大动作 ==========
  if (bodyState == BODY_BREATHING || bodyState == BODY_PAUSED) {
    if (now >= nextBigActionMs) {
      // 设置下次大动作时间
      nextBigActionMs = now + randInt(BIG_ACTION_INTERVAL_MIN, BIG_ACTION_INTERVAL_MAX);
      
      // 35% 概率触发大动作
      if (randFloat(0, 1) < BIG_ACTION_PROB) {
        // 50% 屁股，50% 翅膀
        if (randFloat(0, 1) < 0.5f) {
          bodyState = BODY_BUTT_WIGGLE;
          bodyActionCount = randInt(BUTT_WIGGLE_COUNT_MIN, BUTT_WIGGLE_COUNT_MAX);
        } else {
          bodyState = BODY_WING_FLAP;
          bodyActionCount = randInt(WING_FLAP_COUNT_MIN, WING_FLAP_COUNT_MAX);
        }
        bodyActionStep = 0;
        bodyActionStartMs = now;
        return;
      }
    }
  }
  
  // ========== 呼吸微动 ==========
  if (bodyState == BODY_BREATHING) {
    uint32_t elapsed = now - breathStartMs;
    
    // 检查是否完成一个呼吸周期
    if (elapsed >= breathCycleMs) {
      // 25% 概率暂停一会（呼吸感的随机停顿）
      if (randFloat(0, 1) < BREATH_PAUSE_PROB) {
        bodyState = BODY_PAUSED;
        breathPauseEndMs = now + randInt(BREATH_PAUSE_MIN, BREATH_PAUSE_MAX);
        return;
      }
      // 开始新的呼吸周期
      initBodyBreathing(now);
      elapsed = 0;
    }
    
    // 计算呼吸进度 (0 -> 1 -> 0)
    float t = (float)elapsed / breathCycleMs;
    float breathWave = easeBreath(t);  // 正弦波呼吸
    
    // 翅膀呼吸（小幅度，从中立位上下波动）
    // 两翅膀稍微错开相位，更自然
    float wingWaveA = easeBreath(t);
    float wingWaveB = easeBreath(fmodf(t + breathPhaseOffset, 1.0f));
    
    // 右翅膀：90 ± WING_BREATH_AMP (向上时变小，向下时变大)
    faceAnim.wingA = clampWingA(WING_A_NEUTRAL + (int)(WING_BREATH_AMP * (wingWaveA * 2 - 1)));
    // 左翅膀：90 ± WING_BREATH_AMP (向上时变大，向下时变小)
    faceAnim.wingB = clampWingB(WING_B_NEUTRAL + (int)(WING_BREATH_AMP * (wingWaveB * 2 - 1)));
    
    // 屁股呼吸（更小幅度）
    float buttWave = easeBreath(fmodf(t + 0.5f, 1.0f));  // 和翅膀错开半个周期
    faceAnim.butt = clampButt(BUTT_NEUTRAL + (int)(BUTT_BREATH_AMP * (buttWave * 2 - 1)));
    
    return;
  }
  
  // ========== 暂停状态 ==========
  if (bodyState == BODY_PAUSED) {
    // 保持当前位置
    if (now >= breathPauseEndMs) {
      // 暂停结束，恢复呼吸
      initBodyBreathing(now);
    }
    return;
  }
  
  // ========== 大动作：翅膀扑腾 ==========
  uint32_t elapsed = now - bodyActionStartMs;
  
  if (bodyState == BODY_WING_FLAP) {
    uint8_t curCycle = bodyActionStep / 2;
    bool up = (bodyActionStep % 2 == 0);
    
    if (curCycle < bodyActionCount) {
      if (elapsed < WING_FLAP_DURATION) {
        // 使用贝塞尔曲线平滑
        float t = easeBezier((float)elapsed / WING_FLAP_DURATION);
        if (up) {
          // 从中立位向上扑
          faceAnim.wingA = clampWingA(WING_A_NEUTRAL - (int)(WING_FLAP_AMP * t));
          faceAnim.wingB = clampWingB(WING_B_NEUTRAL + (int)(WING_FLAP_AMP * t));
        } else {
          // 从上回到中立位
          faceAnim.wingA = clampWingA(WING_A_NEUTRAL - WING_FLAP_AMP + (int)(WING_FLAP_AMP * t));
          faceAnim.wingB = clampWingB(WING_B_NEUTRAL + WING_FLAP_AMP - (int)(WING_FLAP_AMP * t));
        }
      } else {
        bodyActionStep++;
        bodyActionStartMs = now;
      }
    } else {
      // 扑腾完成，平滑回到中立位
      faceAnim.wingA = WING_A_NEUTRAL;
      faceAnim.wingB = WING_B_NEUTRAL;
      initBodyBreathing(now);
    }
    return;
  }
  
  // ========== 大动作：屁股翘起 ==========
  if (bodyState == BODY_BUTT_WIGGLE) {
    uint8_t curCycle = bodyActionStep / 3;
    uint8_t phase = bodyActionStep % 3;
    
    if (curCycle < bodyActionCount) {
      if (phase == 0) {
        // 平滑上翘
        if (elapsed < BUTT_UP_DURATION) {
          float t = easeBezier((float)elapsed / BUTT_UP_DURATION);
          faceAnim.butt = clampButt(BUTT_NEUTRAL - (int)(BUTT_WIGGLE_AMP * t));
        } else {
          bodyActionStep++;
          bodyActionStartMs = now;
        }
      } else if (phase == 1) {
        // 短暂停留
        faceAnim.butt = clampButt(BUTT_NEUTRAL - BUTT_WIGGLE_AMP);
        if (elapsed >= BUTT_HOLD_DURATION) {
          bodyActionStep++;
          bodyActionStartMs = now;
        }
      } else {
        // 平滑下降
        if (elapsed < BUTT_DOWN_DURATION) {
          float t = easeBezier((float)elapsed / BUTT_DOWN_DURATION);
          faceAnim.butt = clampButt(BUTT_NEUTRAL - BUTT_WIGGLE_AMP + (int)(BUTT_WIGGLE_AMP * t));
        } else {
          bodyActionStep++;
          bodyActionStartMs = now;
        }
      }
    } else {
      // 翘屁股完成，回到中立位
      faceAnim.butt = BUTT_NEUTRAL;
      initBodyBreathing(now);
    }
  }
}

// ==================== 脖子舵机随机微动 ====================
// ★ 关键改进：只在动作开始时发送一次命令，让 SCServo 自己完成平滑运动
// ★ SCServo 内置速度和加速度控制，不需要每帧插值
// 1号舵机：左右随机摆动，偶尔大幅度转动
// 2、3号舵机：配合俯仰，大幅度动作，保持4号舵机水平
// 4号舵机：偶尔摇头晃脑（左右反复）

// 计算适合的舵机速度（根据距离和期望时间）
// SCServo 速度单位大约是 0.732度/秒 per unit (4096步=360度, 速度单位=步/秒)
// 期望时间 durationMs，距离 distance（SCServo单位），返回合适的速度
int calcNeckSpeed(int distance, int durationMs) {
  if (durationMs <= 0) return 500;
  distance = abs(distance);
  // 速度 = 距离 / 时间(秒) = distance / (durationMs / 1000)
  int speed = (int)(distance * 1000.0f / durationMs);
  // 限制在合理范围
  return constrain(speed, 80, 1500);
}

void updateNeckMove(uint32_t now) {
  
  // ========== 4号舵机摇头晃脑 ==========
  if (faceAnim.neck4Shaking) {
    uint32_t shakeElapsed = now - faceAnim.neck4ShakeStartMs;
    
    // 等待当前摇头动作完成
    if (shakeElapsed >= NECK4_SHAKE_DURATION) {
      // 当前摇头完成，切换方向
      faceAnim.neck4Current = faceAnim.neck4End;
      faceAnim.neck4ShakePhase = 1 - faceAnim.neck4ShakePhase;
      
      if (faceAnim.neck4ShakePhase == 0) {
        faceAnim.neck4ShakeCount--;
      }
      
      if (faceAnim.neck4ShakeCount > 0) {
        // 继续下一次摇头 - 只发送一次命令
        faceAnim.neck4Start = faceAnim.neck4Current;
        if (faceAnim.neck4ShakePhase == 0) {
          faceAnim.neck4End = 2047 - NECK4_SHAKE_AMP;
        } else {
          faceAnim.neck4End = 2047 + NECK4_SHAKE_AMP;
        }
        faceAnim.neck4ShakeStartMs = now;
        
        // ★ 只发送一次命令，让舵机自己完成运动
        int dist4 = abs(faceAnim.neck4End - faceAnim.neck4Start);
        int speed4 = calcNeckSpeed(dist4, NECK4_SHAKE_DURATION);
        setNeckServoCmd(4, faceAnim.neck4End, speed4, 50);
        
      } else {
        // 摇头完成，回到中位
        faceAnim.neck4Shaking = false;
        faceAnim.neck4End = 2047;
        int dist4 = abs(faceAnim.neck4End - faceAnim.neck4Current);
        int speed4 = calcNeckSpeed(dist4, 400);
        setNeckServoCmd(4, faceAnim.neck4End, speed4, 30);
        faceAnim.neck4Current = 2047;
      }
    }
  }
  
  // ========== 检查是否开始新的微动 ==========
  if (!faceAnim.neckMoving) {
    if (now >= faceAnim.neckMoveNextMs) {
      // 开始新的微动
      faceAnim.neckMoving = true;
      faceAnim.neckMoveStartMs = now;
      
      // ========== 1号舵机（左右旋转）==========
      faceAnim.neck1Start = faceAnim.neck1Current;
      
      if (randFloat(0, 1) < NECK1_BIG_MOVE_PROB) {
        // ★ 大幅度左右转动
        faceAnim.neck1BigMove = true;
        int neck1Offset = randInt(-NECK1_BIG_MOVE_AMP, NECK1_BIG_MOVE_AMP);
        if (abs(neck1Offset) < NECK1_BIG_MOVE_AMP / 2) {
          neck1Offset = (neck1Offset > 0 ? 1 : -1) * NECK1_BIG_MOVE_AMP / 2;
        }
        faceAnim.neck1End = 2025 + neck1Offset;
        faceAnim.neckMoveDuration = NECK1_BIG_MOVE_DURATION;
      } else {
        // 普通微动
        faceAnim.neck1BigMove = false;
        int neck1Offset = randInt(-NECK1_MOVE_AMP, NECK1_MOVE_AMP);
        faceAnim.neck1End = 2025 + neck1Offset;
        faceAnim.neckMoveDuration = NECK_MOVE_DURATION;
      }
      faceAnim.neck1End = constrain(faceAnim.neck1End, 1600, 2450);
      
      // ========== 2、3号舵机（俯仰）==========
      faceAnim.neck23Start = faceAnim.neck23Current;
      int neck23Offset = randInt(-NECK23_MOVE_AMP, NECK23_MOVE_AMP);
      faceAnim.neck23End = 2047 + neck23Offset;
      faceAnim.neck23End = constrain(faceAnim.neck23End, 1900, 2200);
      
      // ========== 4号舵机 ==========
      if (!faceAnim.neck4Shaking) {
        if (randFloat(0, 1) < NECK4_SHAKE_PROB) {
          // ★ 开始摇头晃脑
          faceAnim.neck4Shaking = true;
          faceAnim.neck4ShakeCount = randInt(NECK4_SHAKE_COUNT_MIN, NECK4_SHAKE_COUNT_MAX);
          faceAnim.neck4ShakePhase = random(2);
          faceAnim.neck4Start = faceAnim.neck4Current;
          if (faceAnim.neck4ShakePhase == 0) {
            faceAnim.neck4End = 2047 - NECK4_SHAKE_AMP;
          } else {
            faceAnim.neck4End = 2047 + NECK4_SHAKE_AMP;
          }
          faceAnim.neck4ShakeStartMs = now;
          
          // ★ 第一次摇头命令
          int dist4 = abs(faceAnim.neck4End - faceAnim.neck4Start);
          int speed4 = calcNeckSpeed(dist4, NECK4_SHAKE_DURATION);
          setNeckServoCmd(4, faceAnim.neck4End, speed4, 50);
          
        } else {
          // 普通微动
          faceAnim.neck4Start = faceAnim.neck4Current;
          int neck4Offset = randInt(-NECK4_MOVE_AMP, NECK4_MOVE_AMP);
          faceAnim.neck4End = 2047 + neck4Offset;
          faceAnim.neck4End = constrain(faceAnim.neck4End, 1980, 2120);
          
          // ★ 发送4号舵机命令
          int dist4 = abs(faceAnim.neck4End - faceAnim.neck4Start);
          int speed4 = calcNeckSpeed(dist4, faceAnim.neckMoveDuration);
          setNeckServoCmd(4, faceAnim.neck4End, speed4, 30);
        }
      }
      
      // ★★★ 关键：只在动作开始时发送一次命令 ★★★
      // 1号舵机
      int dist1 = abs(faceAnim.neck1End - faceAnim.neck1Start);
      int speed1 = calcNeckSpeed(dist1, faceAnim.neckMoveDuration);
      setNeckServoCmd(1, faceAnim.neck1End, speed1, 30);
      
      // 2、3号舵机（同时同向）
      int dist23 = abs(faceAnim.neck23End - faceAnim.neck23Start);
      int speed23 = calcNeckSpeed(dist23, NECK23_MOVE_DURATION);
      setNeckServoCmd(2, faceAnim.neck23End, speed23, 30);
      setNeckServoCmd(3, faceAnim.neck23End, speed23, 30);
      
      // 更新当前位置记录（用于下次计算起点）
      faceAnim.neck1Current = faceAnim.neck1End;
      faceAnim.neck23Current = faceAnim.neck23End;
      if (!faceAnim.neck4Shaking) {
        faceAnim.neck4Current = faceAnim.neck4End;
      }
    }
    return;
  }
  
  // ========== 等待动作完成 ==========
  uint32_t elapsed = now - faceAnim.neckMoveStartMs;
  
  if (elapsed >= faceAnim.neckMoveDuration) {
    // 动作完成（舵机自己已经完成了运动）
    faceAnim.neckMoving = false;
    faceAnim.neck1BigMove = false;
    
    // 设置下次微动时间
    faceAnim.neckMoveNextMs = now + randInt(NECK_MOVE_INTERVAL_MIN, NECK_MOVE_INTERVAL_MAX);
  }
  // 不需要每帧更新，舵机自己会完成平滑运动
}

// ==================== 情绪: 生气 ====================
// ★ 嘴部动作：上嘴唇压低，右嘴角翘起（撇嘴）
void updateEmotionAngry(uint32_t now) {
  uint32_t elapsed = now - faceAnim.emotionStepMs;
  int rangeUD = EYE_UD_MAX - EYE_UD_MIN;
  
  switch (faceAnim.emotionStep) {
    case 0: {
      // 进入生气表情
      // ★ 只有在语音没有播放时才激活表情嘴部控制（语音嘴巴有最高优先级）
      if (!faceAnim.audioMouthActive) {
        faceAnim.exprMouthActive = true;
      }
      
      if (elapsed < EMOTION_TRANS_MS) {
        float t = easeInOut((float)elapsed / EMOTION_TRANS_MS);
        faceAnim.lidRotL = faceAnim.emotionStartRotL + (int)((LID_ROT_L_ANGRY - faceAnim.emotionStartRotL) * t);
        faceAnim.lidRotR = faceAnim.emotionStartRotR + (int)((LID_ROT_R_ANGRY - faceAnim.emotionStartRotR) * t);
        faceAnim.eyelidL = EYELID_L_NORMAL + (int)((ANGRY_EYELID_L - EYELID_L_NORMAL) * t);
        faceAnim.eyelidR = EYELID_R_NORMAL + (int)((ANGRY_EYELID_R - EYELID_R_NORMAL) * t);
        faceAnim.eyeUD = 90 + (int)((EYE_UD_MAX - rangeUD * 0.3f - 90) * t);
        // 翅膀张开（威胁姿态）- 从中立位向上展开
        faceAnim.wingA = clampWingA(WING_A_NEUTRAL - (int)(40 * t));
        faceAnim.wingB = clampWingB(WING_B_NEUTRAL + (int)(40 * t));
        
        // ★ 嘴部过渡：上嘴唇压低，右嘴角撇，左嘴角保持
        faceAnim.mouthR = MOUTH_R_NEUTRAL + (int)((MOUTH_EXPR_ANGRY.rightCorner - MOUTH_R_NEUTRAL) * t);
        faceAnim.mouthL = MOUTH_L_NEUTRAL + (int)((MOUTH_EXPR_ANGRY.leftCorner - MOUTH_L_NEUTRAL) * t);
        faceAnim.mouthU = MOUTH_U_NEUTRAL + (int)((MOUTH_EXPR_ANGRY.upperLip - MOUTH_U_NEUTRAL) * t);
        faceAnim.mouthLower = MOUTH_LOWER_CLOSED + (int)((MOUTH_EXPR_ANGRY.lowerLip - MOUTH_LOWER_CLOSED) * t);
      } else {
        faceAnim.emotionStep = 1;
        faceAnim.emotionStepMs = now;
      }
      break;
    }
    case 1: {
      // 快速扫视 + 嘴巴活动 + 翅膀抖动
      if ((elapsed / 150) % 2 == 0) {
        faceAnim.eyeLR = 90 + randInt(-40, 40);
      }
      
      // ★ 持续维护嘴角的歪嘴表情 + 上嘴唇抽动效果
      if (!faceAnim.audioMouthActive) {
        // 保持歪嘴表情：右嘴角上扬，左嘴角下弯
        faceAnim.mouthR = MOUTH_EXPR_ANGRY.rightCorner;
        faceAnim.mouthL = MOUTH_EXPR_ANGRY.leftCorner;
        
        // ★ 上嘴唇来回抽动（模仿嘴巴抽抽的感觉）
        // 周期约200ms，上嘴唇在 95-112 之间快速抖动
        float lipTwitch = sinf((float)(now % 200) / 200.0f * 3.14159f * 2.0f);
        faceAnim.mouthU = 103 + (int)(lipTwitch * 9);  // 94 ~ 112 范围抖动
        
        // 偶尔张嘴咆哮
        if (random(100) < 25) {
          faceAnim.mouth = MOUTH_CLOSED + (MOUTH_MAX_OPEN - MOUTH_CLOSED) / 2;
          faceAnim.mouthLower = MOUTH_EXPR_ANGRY.lowerLip + randInt(0, 15);
        } else {
          faceAnim.mouth = MOUTH_CLOSED;
          faceAnim.mouthLower = MOUTH_EXPR_ANGRY.lowerLip;
        }
      }
      
      faceAnim.eyelidL = ANGRY_EYELID_L + randInt(-5, 5);
      faceAnim.eyelidR = ANGRY_EYELID_R + randInt(-5, 5);
      
      // 翅膀快速抖动（愤怒姿态）
      float wingJitter = sinf((float)(now % 100) / 100.0f * 3.14159f * 2.0f) * 8;
      faceAnim.wingA = clampWingA(WING_A_NEUTRAL - 30 + (int)wingJitter);
      faceAnim.wingB = clampWingB(WING_B_NEUTRAL + 30 - (int)wingJitter);
      
      if (now >= faceAnim.emotionEndMs) {
        faceAnim.emotionStep = 2;
        faceAnim.emotionStepMs = now;
      }
      break;
    }
    case 2: {
      if (elapsed < EMOTION_TRANS_MS / 2) {
        float t = easeInOut((float)elapsed / (EMOTION_TRANS_MS / 2));
        faceAnim.lidRotL = LID_ROT_L_ANGRY + (int)((LID_ROT_L_NORMAL - LID_ROT_L_ANGRY) * t);
        faceAnim.lidRotR = LID_ROT_R_ANGRY + (int)((LID_ROT_R_NORMAL - LID_ROT_R_ANGRY) * t);
        faceAnim.eyelidL = ANGRY_EYELID_L + (int)((EYELID_L_NORMAL - ANGRY_EYELID_L) * t);
        faceAnim.eyelidR = ANGRY_EYELID_R + (int)((EYELID_R_NORMAL - ANGRY_EYELID_R) * t);
        faceAnim.eyeUD = faceAnim.eyeUD + (int)((90 - faceAnim.eyeUD) * t);
        faceAnim.eyeLR = faceAnim.eyeLR + (int)((90 - faceAnim.eyeLR) * t);
        faceAnim.mouth = faceAnim.mouth + (int)((MOUTH_CLOSED - faceAnim.mouth) * t);
        // 翅膀收回到中立位
        faceAnim.wingA = faceAnim.wingA + (int)((WING_A_NEUTRAL - faceAnim.wingA) * t);
        faceAnim.wingB = faceAnim.wingB + (int)((WING_B_NEUTRAL - faceAnim.wingB) * t);
        
        // ★ 嘴部复位
        faceAnim.mouthR = faceAnim.mouthR + (int)((MOUTH_R_NEUTRAL - faceAnim.mouthR) * t);
        faceAnim.mouthL = faceAnim.mouthL + (int)((MOUTH_L_NEUTRAL - faceAnim.mouthL) * t);
        faceAnim.mouthU = faceAnim.mouthU + (int)((MOUTH_U_NEUTRAL - faceAnim.mouthU) * t);
        faceAnim.mouthLower = faceAnim.mouthLower + (int)((MOUTH_LOWER_CLOSED - faceAnim.mouthLower) * t);
      } else {
        faceAnim.currentEmotion = EMO_IDLE;
        faceAnim.eyeState = EYE_IDLE;
        faceAnim.wingA = WING_A_NEUTRAL;
        faceAnim.wingB = WING_B_NEUTRAL;
        // ★ 重置嘴巴到闭合状态
        faceAnim.mouthR = MOUTH_R_NEUTRAL;
        faceAnim.mouthL = MOUTH_L_NEUTRAL;
        faceAnim.mouthU = MOUTH_U_NEUTRAL;
        faceAnim.mouthLower = MOUTH_LOWER_CLOSED;
        faceAnim.exprMouthActive = false;  // 关闭表情嘴部控制
        initBodyBreathing(now);
        eyeMicroNextMs = now + 500; eyeBigNextMs = now + 2000;
      }
      break;
    }
  }
}

// ==================== 情绪: 伤心 ====================
// ★ 嘴部动作：嘴角下撇，委屈表情
void updateEmotionSad(uint32_t now) {
  uint32_t elapsed = now - faceAnim.emotionStepMs;
  int rangeUD = EYE_UD_MAX - EYE_UD_MIN;
  
  switch (faceAnim.emotionStep) {
    case 0: {
      // ★ 只有在语音没有播放时才激活表情嘴部控制（语音嘴巴有最高优先级）
      if (!faceAnim.audioMouthActive) {
        faceAnim.exprMouthActive = true;
      }
      
      if (elapsed < EMOTION_TRANS_MS) {
        float t = easeInOut((float)elapsed / EMOTION_TRANS_MS);
        faceAnim.lidRotL = faceAnim.emotionStartRotL + (int)((LID_ROT_L_SAD - faceAnim.emotionStartRotL) * t);
        faceAnim.lidRotR = faceAnim.emotionStartRotR + (int)((LID_ROT_R_SAD - faceAnim.emotionStartRotR) * t);
        faceAnim.eyelidL = EYELID_L_NORMAL + (int)((SAD_EYELID_L - EYELID_L_NORMAL) * t);
        faceAnim.eyelidR = EYELID_R_NORMAL + (int)((SAD_EYELID_R - EYELID_R_NORMAL) * t);
        faceAnim.eyeUD = 90 + (int)((EYE_UD_MIN + rangeUD * 0.3f - 90) * t);
        // 翅膀稍微下垂（悲伤姿态）
        faceAnim.wingA = clampWingA(WING_A_NEUTRAL + (int)(15 * t));  // 稍微向下
        faceAnim.wingB = clampWingB(WING_B_NEUTRAL - (int)(15 * t));
        // 屁股稍微下垂
        faceAnim.butt = clampButt(BUTT_NEUTRAL + (int)(10 * t));
        
        // ★ 嘴部过渡：嘴角下撇
        faceAnim.mouthR = MOUTH_R_NEUTRAL + (int)((MOUTH_EXPR_SAD.rightCorner - MOUTH_R_NEUTRAL) * t);
        faceAnim.mouthL = MOUTH_L_NEUTRAL + (int)((MOUTH_EXPR_SAD.leftCorner - MOUTH_L_NEUTRAL) * t);
        faceAnim.mouthU = MOUTH_U_NEUTRAL + (int)((MOUTH_EXPR_SAD.upperLip - MOUTH_U_NEUTRAL) * t);
        faceAnim.mouthLower = MOUTH_LOWER_CLOSED + (int)((MOUTH_EXPR_SAD.lowerLip - MOUTH_LOWER_CLOSED) * t);
      } else {
        faceAnim.emotionStep = 1;
        faceAnim.emotionStepMs = now;
      }
      break;
    }
    case 1: {
      // 缓慢移动眼球 + 翅膀偶尔小幅抖动
      if ((elapsed / 1000) % 2 == 0 && random(100) < 60) {
        if (randFloat(0, 1) < SAD_EYE_DOWN_PROB) {
          faceAnim.eyeUD = EYE_UD_MIN + randInt(5, (int)(rangeUD * 0.4f));
        }
        faceAnim.eyeLR = 90 + randInt(-20, 20);
      }
      faceAnim.eyelidL = SAD_EYELID_L + randInt(-3, 3);
      faceAnim.eyelidR = SAD_EYELID_R + randInt(-3, 3);
      
      // ★ 持续维护嘴角和上嘴唇的嘟嘴/撇嘴表情
      if (!faceAnim.audioMouthActive) {
        faceAnim.mouthR = MOUTH_EXPR_SAD.rightCorner;
        faceAnim.mouthL = MOUTH_EXPR_SAD.leftCorner;
        faceAnim.mouthU = MOUTH_EXPR_SAD.upperLip;
        faceAnim.mouthLower = MOUTH_EXPR_SAD.lowerLip;
      }
      
      // 偶尔翅膀小幅抖动（像在叹气）
      if (random(100) < 3) {
        faceAnim.wingA = clampWingA(WING_A_NEUTRAL + 15 - randInt(0, 10));
        faceAnim.wingB = clampWingB(WING_B_NEUTRAL - 15 + randInt(0, 10));
      } else {
        faceAnim.wingA = clampWingA(WING_A_NEUTRAL + 15);
        faceAnim.wingB = clampWingB(WING_B_NEUTRAL - 15);
      }
      
      if (now >= faceAnim.emotionEndMs) {
        faceAnim.emotionStep = 2;
        faceAnim.emotionStepMs = now;
      }
      break;
    }
    case 2: {
      if (elapsed < EMOTION_TRANS_MS / 2) {
        float t = easeInOut((float)elapsed / (EMOTION_TRANS_MS / 2));
        faceAnim.lidRotL = LID_ROT_L_SAD + (int)((LID_ROT_L_NORMAL - LID_ROT_L_SAD) * t);
        faceAnim.lidRotR = LID_ROT_R_SAD + (int)((LID_ROT_R_NORMAL - LID_ROT_R_SAD) * t);
        faceAnim.eyelidL = SAD_EYELID_L + (int)((EYELID_L_NORMAL - SAD_EYELID_L) * t);
        faceAnim.eyelidR = SAD_EYELID_R + (int)((EYELID_R_NORMAL - SAD_EYELID_R) * t);
        faceAnim.eyeUD = faceAnim.eyeUD + (int)((90 - faceAnim.eyeUD) * t);
        faceAnim.eyeLR = faceAnim.eyeLR + (int)((90 - faceAnim.eyeLR) * t);
        
        // ★ 嘴部复位
        faceAnim.mouthR = faceAnim.mouthR + (int)((MOUTH_R_NEUTRAL - faceAnim.mouthR) * t);
        faceAnim.mouthL = faceAnim.mouthL + (int)((MOUTH_L_NEUTRAL - faceAnim.mouthL) * t);
        faceAnim.mouthU = faceAnim.mouthU + (int)((MOUTH_U_NEUTRAL - faceAnim.mouthU) * t);
        faceAnim.mouthLower = faceAnim.mouthLower + (int)((MOUTH_LOWER_CLOSED - faceAnim.mouthLower) * t);
      } else {
        faceAnim.currentEmotion = EMO_IDLE;
        faceAnim.eyeState = EYE_IDLE;
        faceAnim.wingA = WING_A_NEUTRAL;
        faceAnim.wingB = WING_B_NEUTRAL;
        faceAnim.butt = BUTT_NEUTRAL;
        // ★ 重置嘴巴到闭合状态
        faceAnim.mouthR = MOUTH_R_NEUTRAL;
        faceAnim.mouthL = MOUTH_L_NEUTRAL;
        faceAnim.mouthU = MOUTH_U_NEUTRAL;
        faceAnim.mouthLower = MOUTH_LOWER_CLOSED;
        faceAnim.exprMouthActive = false;  // 关闭表情嘴部控制
        initBodyBreathing(now);
        eyeMicroNextMs = now + 500; eyeBigNextMs = now + 2000;
      }
      break;
    }
  }
}

// ==================== 情绪: 开心 ====================
// ★ 嘴部动作：嘴角全部咧开，微笑
void updateEmotionHappy(uint32_t now) {
  uint32_t elapsed = now - faceAnim.emotionStepMs;
  
  switch (faceAnim.emotionStep) {
    case 0: {
      // 过渡：睁大眼睛 + 张嘴 + 翅膀扬起
      // ★ 只有在语音没有播放时才激活表情嘴部控制（语音嘴巴有最高优先级）
      if (!faceAnim.audioMouthActive) {
        faceAnim.exprMouthActive = true;
      }
      
      if (elapsed < EMOTION_TRANS_MS / 2) {
        float t = easeInOut((float)elapsed / (EMOTION_TRANS_MS / 2));
        faceAnim.lidRotL = faceAnim.emotionStartRotL + (int)((HAPPY_ROT_L - faceAnim.emotionStartRotL) * t);
        faceAnim.lidRotR = faceAnim.emotionStartRotR + (int)((HAPPY_ROT_R - faceAnim.emotionStartRotR) * t);
        faceAnim.eyelidL = EYELID_L_NORMAL + (int)((HAPPY_EYELID_L - EYELID_L_NORMAL) * t);
        faceAnim.eyelidR = EYELID_R_NORMAL + (int)((HAPPY_EYELID_R - EYELID_R_NORMAL) * t);
        // 翅膀扬起（从中立位向上）
        faceAnim.wingA = clampWingA(WING_A_NEUTRAL - (int)(35 * t));
        faceAnim.wingB = clampWingB(WING_B_NEUTRAL + (int)(35 * t));
        if (!faceAnim.audioMouthActive) {
          faceAnim.mouth = MOUTH_CLOSED + (int)((HAPPY_MOUTH_OPEN - MOUTH_CLOSED) * t);
        }
        
        // ★ 嘴部过渡：嘴角咧开，微笑
        faceAnim.mouthR = MOUTH_R_NEUTRAL + (int)((MOUTH_EXPR_HAPPY.rightCorner - MOUTH_R_NEUTRAL) * t);
        faceAnim.mouthL = MOUTH_L_NEUTRAL + (int)((MOUTH_EXPR_HAPPY.leftCorner - MOUTH_L_NEUTRAL) * t);
        faceAnim.mouthU = MOUTH_U_NEUTRAL + (int)((MOUTH_EXPR_HAPPY.upperLip - MOUTH_U_NEUTRAL) * t);
        faceAnim.mouthLower = MOUTH_LOWER_CLOSED + (int)((MOUTH_EXPR_HAPPY.lowerLip - MOUTH_LOWER_CLOSED) * t);
      } else {
        faceAnim.emotionStep = 1;
        faceAnim.emotionStepMs = now;
      }
      break;
    }
    case 1: {
      // 笑的动作：眼皮保持睁大 + 翅膀扑腾 + 眼球晃动
      faceAnim.eyelidL = HAPPY_EYELID_L;
      faceAnim.eyelidR = HAPPY_EYELID_R;
      
      float swing = sinf((float)(now % 500) / 500.0f * 3.14159f * 2.0f) * HAPPY_ROT_SWING;
      faceAnim.lidRotL = HAPPY_ROT_L + (int)swing;
      faceAnim.lidRotR = HAPPY_ROT_R - (int)swing;
      faceAnim.eyeLR = 90 + (int)(sinf((float)(now % 300) / 300.0f * 3.14159f * 2.0f) * 25);
      
      // 翅膀快速扑腾（平滑的正弦波）
      float wingPhase = sinf((float)(now % 250) / 250.0f * 3.14159f * 2.0f);
      faceAnim.wingA = clampWingA(WING_A_NEUTRAL - 30 + (int)(15 * wingPhase));
      faceAnim.wingB = clampWingB(WING_B_NEUTRAL + 30 - (int)(15 * wingPhase));
      
      // ★ 持续维护嘴角和上嘴唇的微笑表情
      if (!faceAnim.audioMouthActive) {
        // 保持咧嘴微笑：嘴角上扬，上嘴唇上扬
        faceAnim.mouthR = MOUTH_EXPR_HAPPY.rightCorner;
        faceAnim.mouthL = MOUTH_EXPR_HAPPY.leftCorner;
        faceAnim.mouthU = MOUTH_EXPR_HAPPY.upperLip;
        
        faceAnim.mouth = HAPPY_MOUTH_OPEN + randInt(-10, 10);
        faceAnim.mouthLower = MOUTH_EXPR_HAPPY.lowerLip + randInt(-5, 10);
      }
      
      if (now >= faceAnim.emotionEndMs) {
        faceAnim.emotionStep = 2;
        faceAnim.emotionStepMs = now;
      }
      break;
    }
    case 2: {
      // 恢复
      if (elapsed < EMOTION_TRANS_MS / 2) {
        float t = easeInOut((float)elapsed / (EMOTION_TRANS_MS / 2));
        faceAnim.lidRotL = HAPPY_ROT_L + (int)((LID_ROT_L_NORMAL - HAPPY_ROT_L) * t);
        faceAnim.lidRotR = HAPPY_ROT_R + (int)((LID_ROT_R_NORMAL - HAPPY_ROT_R) * t);
        faceAnim.eyelidL = HAPPY_EYELID_L + (int)((EYELID_L_NORMAL - HAPPY_EYELID_L) * t);
        faceAnim.eyelidR = HAPPY_EYELID_R + (int)((EYELID_R_NORMAL - HAPPY_EYELID_R) * t);
        faceAnim.mouth = faceAnim.mouth + (int)((MOUTH_CLOSED - faceAnim.mouth) * t);
        faceAnim.eyeLR = faceAnim.eyeLR + (int)((90 - faceAnim.eyeLR) * t);
        // 翅膀收回到中立位
        faceAnim.wingA = faceAnim.wingA + (int)((WING_A_NEUTRAL - faceAnim.wingA) * t);
        faceAnim.wingB = faceAnim.wingB + (int)((WING_B_NEUTRAL - faceAnim.wingB) * t);
        
        // ★ 嘴部复位
        faceAnim.mouthR = faceAnim.mouthR + (int)((MOUTH_R_NEUTRAL - faceAnim.mouthR) * t);
        faceAnim.mouthL = faceAnim.mouthL + (int)((MOUTH_L_NEUTRAL - faceAnim.mouthL) * t);
        faceAnim.mouthU = faceAnim.mouthU + (int)((MOUTH_U_NEUTRAL - faceAnim.mouthU) * t);
        faceAnim.mouthLower = faceAnim.mouthLower + (int)((MOUTH_LOWER_CLOSED - faceAnim.mouthLower) * t);
      } else {
        faceAnim.currentEmotion = EMO_IDLE;
        faceAnim.eyeState = EYE_IDLE;
        faceAnim.wingA = WING_A_NEUTRAL;
        faceAnim.wingB = WING_B_NEUTRAL;
        // ★ 重置嘴巴到闭合状态
        faceAnim.mouthR = MOUTH_R_NEUTRAL;
        faceAnim.mouthL = MOUTH_L_NEUTRAL;
        faceAnim.mouthU = MOUTH_U_NEUTRAL;
        faceAnim.mouthLower = MOUTH_LOWER_CLOSED;
        faceAnim.exprMouthActive = false;  // 关闭表情嘴部控制
        initBodyBreathing(now);
        eyeMicroNextMs = now + 500; eyeBigNextMs = now + 2000;
      }
      break;
    }
  }
}

// ==================== 情绪: 无语 ====================
// ★ 嘴部动作：嘴角下撇，上嘴唇最高，闭嘴
void updateEmotionSpeechless(uint32_t now) {
  uint32_t elapsed = now - faceAnim.emotionStepMs;
  
  switch (faceAnim.emotionStep) {
    case 0: {
      // 眯眼 + 眼皮旋转复位 + 翅膀摊开（无奈姿态）
      // ★ 只有在语音没有播放时才激活表情嘴部控制（语音嘴巴有最高优先级）
      if (!faceAnim.audioMouthActive) {
        faceAnim.exprMouthActive = true;
      }
      
      if (elapsed < 300) {
        float t = (float)elapsed / 300;
        faceAnim.eyelidL = EYELID_L_NORMAL + (int)((SPEECHLESS_EYELID_L - EYELID_L_NORMAL) * t);
        faceAnim.eyelidR = EYELID_R_NORMAL + (int)((SPEECHLESS_EYELID_R - EYELID_R_NORMAL) * t);
        // 眼皮旋转复位到正常位置
        faceAnim.lidRotL = faceAnim.emotionStartRotL + (int)((LID_ROT_L_NORMAL - faceAnim.emotionStartRotL) * t);
        faceAnim.lidRotR = faceAnim.emotionStartRotR + (int)((LID_ROT_R_NORMAL - faceAnim.emotionStartRotR) * t);
        // 翅膀微微张开（无奈摊手）
        faceAnim.wingA = clampWingA(WING_A_NEUTRAL - (int)(20 * t));
        faceAnim.wingB = clampWingB(WING_B_NEUTRAL + (int)(20 * t));
        
        // ★ 嘴部过渡：歪嘴效果（右上扬左下弯）
        faceAnim.mouthR = MOUTH_R_NEUTRAL + (int)((MOUTH_EXPR_SPEECHLESS.rightCorner - MOUTH_R_NEUTRAL) * t);
        faceAnim.mouthL = MOUTH_L_NEUTRAL + (int)((MOUTH_EXPR_SPEECHLESS.leftCorner - MOUTH_L_NEUTRAL) * t);
        faceAnim.mouthU = MOUTH_U_NEUTRAL + (int)((MOUTH_EXPR_SPEECHLESS.upperLip - MOUTH_U_NEUTRAL) * t);
        faceAnim.mouthLower = MOUTH_LOWER_CLOSED + (int)((MOUTH_EXPR_SPEECHLESS.lowerLip - MOUTH_LOWER_CLOSED) * t);
      } else {
        // 确保眼皮旋转完全复位
        faceAnim.lidRotL = LID_ROT_L_NORMAL;
        faceAnim.lidRotR = LID_ROT_R_NORMAL;
        faceAnim.emotionStep = 1;
        faceAnim.emotionStepMs = now;
      }
      break;
    }
    case 1: {
      // 眼球向上翻
      // ★ 持续维护嘴部歪嘴表情（静止不抽动）
      if (!faceAnim.audioMouthActive) {
        faceAnim.mouthR = MOUTH_EXPR_SPEECHLESS.rightCorner;
        faceAnim.mouthL = MOUTH_EXPR_SPEECHLESS.leftCorner;
        faceAnim.mouthU = MOUTH_EXPR_SPEECHLESS.upperLip;
        faceAnim.mouthLower = MOUTH_EXPR_SPEECHLESS.lowerLip;
      }
      
      if (elapsed < 600) {
        float t = easeInOut((float)elapsed / 600);
        faceAnim.eyeUD = 90 + (int)((SPEECHLESS_EYE_UP - 90) * t);
      } else {
        faceAnim.emotionStep = 2;
        faceAnim.emotionStepMs = now;
      }
      break;
    }
    case 2: {
      // 回中
      // ★ 持续维护嘴部歪嘴表情
      if (!faceAnim.audioMouthActive) {
        faceAnim.mouthR = MOUTH_EXPR_SPEECHLESS.rightCorner;
        faceAnim.mouthL = MOUTH_EXPR_SPEECHLESS.leftCorner;
        faceAnim.mouthU = MOUTH_EXPR_SPEECHLESS.upperLip;
        faceAnim.mouthLower = MOUTH_EXPR_SPEECHLESS.lowerLip;
      }
      
      if (elapsed < 400) {
        float t = easeInOut((float)elapsed / 400);
        faceAnim.eyeUD = SPEECHLESS_EYE_UP + (int)((90 - SPEECHLESS_EYE_UP) * t);
      } else {
        faceAnim.emotionStep = 3;
        faceAnim.emotionStepMs = now;
        faceAnim.emotionSide = random(2) == 0 ? -1 : 1;
      }
      break;
    }
    case 3: {
      // 向一侧看 + 屁股小幅扭动
      // ★ 持续维护嘴部歪嘴表情
      if (!faceAnim.audioMouthActive) {
        faceAnim.mouthR = MOUTH_EXPR_SPEECHLESS.rightCorner;
        faceAnim.mouthL = MOUTH_EXPR_SPEECHLESS.leftCorner;
        faceAnim.mouthU = MOUTH_EXPR_SPEECHLESS.upperLip;
        faceAnim.mouthLower = MOUTH_EXPR_SPEECHLESS.lowerLip;
      }
      
      if (elapsed < 250) {
        float t = easeInOut((float)elapsed / 250);
        faceAnim.eyeLR = 90 + (int)(faceAnim.emotionSide * 40 * t);
        // 屁股小幅扭动
        faceAnim.butt = clampButt(BUTT_NEUTRAL - (int)(15 * t));
      } else {
        faceAnim.emotionStep = 4;
        faceAnim.emotionStepMs = now;
      }
      break;
    }
    case 4: {
      // 再向上翻白眼 + 屁股回位
      // ★ 持续维护嘴部歪嘴表情
      if (!faceAnim.audioMouthActive) {
        faceAnim.mouthR = MOUTH_EXPR_SPEECHLESS.rightCorner;
        faceAnim.mouthL = MOUTH_EXPR_SPEECHLESS.leftCorner;
        faceAnim.mouthU = MOUTH_EXPR_SPEECHLESS.upperLip;
        faceAnim.mouthLower = MOUTH_EXPR_SPEECHLESS.lowerLip;
      }
      
      if (elapsed < 500) {
        float t = easeInOut((float)elapsed / 500);
        faceAnim.eyeUD = 90 + (int)((SPEECHLESS_EYE_UP - 90) * t);
        faceAnim.eyeLR = faceAnim.eyeLR + (int)((90 - faceAnim.eyeLR) * t);
        faceAnim.butt = faceAnim.butt + (int)((BUTT_NEUTRAL - faceAnim.butt) * t);
      } else if (now >= faceAnim.emotionEndMs) {
        faceAnim.emotionStep = 5;
        faceAnim.emotionStepMs = now;
      }
      break;
    }
    case 5: {
      // 恢复
      if (elapsed < 400) {
        float t = easeInOut((float)elapsed / 400);
        faceAnim.eyelidL = SPEECHLESS_EYELID_L + (int)((EYELID_L_NORMAL - SPEECHLESS_EYELID_L) * t);
        faceAnim.eyelidR = SPEECHLESS_EYELID_R + (int)((EYELID_R_NORMAL - SPEECHLESS_EYELID_R) * t);
        faceAnim.eyeUD = SPEECHLESS_EYE_UP + (int)((90 - SPEECHLESS_EYE_UP) * t);
        // 翅膀收回到中立位
        faceAnim.wingA = faceAnim.wingA + (int)((WING_A_NEUTRAL - faceAnim.wingA) * t);
        faceAnim.wingB = faceAnim.wingB + (int)((WING_B_NEUTRAL - faceAnim.wingB) * t);
        // 眼皮旋转保持正常位置
        faceAnim.lidRotL = LID_ROT_L_NORMAL;
        faceAnim.lidRotR = LID_ROT_R_NORMAL;
        
        // ★ 嘴部复位
        faceAnim.mouthR = faceAnim.mouthR + (int)((MOUTH_R_NEUTRAL - faceAnim.mouthR) * t);
        faceAnim.mouthL = faceAnim.mouthL + (int)((MOUTH_L_NEUTRAL - faceAnim.mouthL) * t);
        faceAnim.mouthU = faceAnim.mouthU + (int)((MOUTH_U_NEUTRAL - faceAnim.mouthU) * t);
        faceAnim.mouthLower = faceAnim.mouthLower + (int)((MOUTH_LOWER_CLOSED - faceAnim.mouthLower) * t);
      } else {
        faceAnim.currentEmotion = EMO_IDLE;
        faceAnim.eyeState = EYE_IDLE;
        faceAnim.wingA = WING_A_NEUTRAL;
        faceAnim.wingB = WING_B_NEUTRAL;
        faceAnim.butt = BUTT_NEUTRAL;
        faceAnim.lidRotL = LID_ROT_L_NORMAL;
        faceAnim.lidRotR = LID_ROT_R_NORMAL;
        // ★ 重置嘴巴到闭合状态
        faceAnim.mouthR = MOUTH_R_NEUTRAL;
        faceAnim.mouthL = MOUTH_L_NEUTRAL;
        faceAnim.mouthU = MOUTH_U_NEUTRAL;
        faceAnim.mouthLower = MOUTH_LOWER_CLOSED;
        faceAnim.exprMouthActive = false;  // 关闭表情嘴部控制
        initBodyBreathing(now);
        eyeMicroNextMs = now + 500; eyeBigNextMs = now + 2000;
      }
      break;
    }
  }
}

// ==================== 情绪: Wink ====================
// ★ 嘴部动作：单边嘴角翘起（俏皮）
void updateEmotionWink(uint32_t now) {
  uint32_t elapsed = now - faceAnim.emotionStepMs;
  
  switch (faceAnim.emotionStep) {
    case 0: {
      // 眼睛张大 + 屁股翘起（俏皮）
      // ★ 只有在语音没有播放时才激活表情嘴部控制（语音嘴巴有最高优先级）
      if (!faceAnim.audioMouthActive) {
        faceAnim.exprMouthActive = true;
      }
      
      faceAnim.eyelidL = EYELID_L_MAX_OPEN;
      faceAnim.eyelidR = EYELID_R_MAX_OPEN;
      faceAnim.lidRotL = LID_ROT_L_NORMAL;
      faceAnim.lidRotR = LID_ROT_R_NORMAL;
      // 屁股稍微翘起（俏皮）
      float t = min(1.0f, (float)elapsed / 200);
      faceAnim.butt = clampButt(BUTT_NEUTRAL - (int)(20 * t));
      
      // ★ 嘴部过渡：单边嘴角翘起
      faceAnim.mouthR = MOUTH_R_NEUTRAL + (int)((MOUTH_EXPR_WINK.rightCorner - MOUTH_R_NEUTRAL) * t);
      faceAnim.mouthL = MOUTH_L_NEUTRAL + (int)((MOUTH_EXPR_WINK.leftCorner - MOUTH_L_NEUTRAL) * t);
      faceAnim.mouthU = MOUTH_U_NEUTRAL + (int)((MOUTH_EXPR_WINK.upperLip - MOUTH_U_NEUTRAL) * t);
      faceAnim.mouthLower = MOUTH_LOWER_CLOSED + (int)((MOUTH_EXPR_WINK.lowerLip - MOUTH_LOWER_CLOSED) * t);
      
      if (elapsed > 200) {
        faceAnim.emotionStep = 1;
        faceAnim.emotionStepMs = now;
        faceAnim.emotionSide = random(2);  // 0=左, 1=右
        faceAnim.emotionCount = randInt(WINK_COUNT_MIN, WINK_COUNT_MAX);
      }
      break;
    }
    case 1: {
      // Wink - 一只眼快速眨 + 翅膀小幅扑腾
      // ★ 持续维护嘴部的俏皮表情
      if (!faceAnim.audioMouthActive) {
        faceAnim.mouthR = MOUTH_EXPR_WINK.rightCorner;
        faceAnim.mouthL = MOUTH_EXPR_WINK.leftCorner;
        faceAnim.mouthU = MOUTH_EXPR_WINK.upperLip;
        faceAnim.mouthLower = MOUTH_EXPR_WINK.lowerLip;
      }
      
      uint32_t cycleDur = WINK_CLOSE_MS + WINK_OPEN_MS + 200;  // 每次眨眼周期
      uint8_t curCycle = elapsed / cycleDur;
      uint32_t phase = elapsed % cycleDur;
      
      if (curCycle < faceAnim.emotionCount) {
        // 眼球随机偏转
        int turnDir = random(2) == 0 ? -1 : 1;
        faceAnim.eyeLR = 90 + turnDir * randInt(WINK_EYE_TURN / 2, WINK_EYE_TURN);
        
        // 确保两只眼睛的状态都被设置
        if (phase < WINK_CLOSE_MS) {
          // 闭眼阶段
          if (faceAnim.emotionSide == 0) {
            faceAnim.eyelidL = EYELID_L_CLOSED;
            faceAnim.eyelidR = EYELID_R_MAX_OPEN;  // 另一只眼保持张开
          } else {
            faceAnim.eyelidR = EYELID_R_CLOSED;
            faceAnim.eyelidL = EYELID_L_MAX_OPEN;  // 另一只眼保持张开
          }
        } else {
          // 睁眼阶段
          faceAnim.eyelidL = EYELID_L_MAX_OPEN;
          faceAnim.eyelidR = EYELID_R_MAX_OPEN;
        }
        
        // 翅膀小幅扑腾（可爱）
        float wingPhase = sinf((float)(now % 300) / 300.0f * 3.14159f * 2.0f);
        faceAnim.wingA = clampWingA(WING_A_NEUTRAL + (int)(10 * wingPhase));
        faceAnim.wingB = clampWingB(WING_B_NEUTRAL - (int)(10 * wingPhase));
      } else {
        faceAnim.emotionStep = 2;
        faceAnim.emotionStepMs = now;
        faceAnim.emotionCount = WINK_MOUTH_COUNT;
      }
      break;
    }
    case 2: {
      // 嘴巴张开 + 屁股扭动
      if (!faceAnim.audioMouthActive) {
        // ★ 持续维护嘴角和上嘴唇的俏皮表情
        faceAnim.mouthR = MOUTH_EXPR_WINK.rightCorner;
        faceAnim.mouthL = MOUTH_EXPR_WINK.leftCorner;
        faceAnim.mouthU = MOUTH_EXPR_WINK.upperLip;
        
        uint32_t mouthCycle = WINK_MOUTH_MS * 2;
        uint8_t curCycle = elapsed / mouthCycle;
        uint32_t phase = elapsed % mouthCycle;
        
        if (curCycle < faceAnim.emotionCount) {
          if (phase < WINK_MOUTH_MS) {
            faceAnim.mouth = MOUTH_CLOSED + (MOUTH_MAX_OPEN - MOUTH_CLOSED) * 7 / 10;
            faceAnim.mouthLower = MOUTH_EXPR_WINK.lowerLip + 15;  // 张嘴时下嘴唇更开
            // 屁股小幅扭动
            faceAnim.butt = clampButt(BUTT_NEUTRAL - 15 + (int)(8 * sinf((float)(now % 200) / 200.0f * 3.14159f * 2.0f)));
          } else {
            faceAnim.mouth = MOUTH_CLOSED;
            faceAnim.mouthLower = MOUTH_EXPR_WINK.lowerLip;
          }
        } else {
          faceAnim.emotionStep = 3;
          faceAnim.emotionStepMs = now;
        }
      } else {
        faceAnim.emotionStep = 3;
        faceAnim.emotionStepMs = now;
      }
      break;
    }
    case 3: {
      // 恢复
      if (elapsed < 300) {
        float t = (float)elapsed / 300;
        faceAnim.eyelidL = EYELID_L_MAX_OPEN + (int)((EYELID_L_NORMAL - EYELID_L_MAX_OPEN) * t);
        faceAnim.eyelidR = EYELID_R_MAX_OPEN + (int)((EYELID_R_NORMAL - EYELID_R_MAX_OPEN) * t);
        faceAnim.eyeLR = faceAnim.eyeLR + (int)((90 - faceAnim.eyeLR) * t * 0.3f);
        faceAnim.mouth = faceAnim.mouth + (int)((MOUTH_CLOSED - faceAnim.mouth) * t * 0.5f);
        // 屁股回位到中立
        faceAnim.butt = faceAnim.butt + (int)((BUTT_NEUTRAL - faceAnim.butt) * t);
        // 翅膀回位到中立
        faceAnim.wingA = faceAnim.wingA + (int)((WING_A_NEUTRAL - faceAnim.wingA) * t);
        faceAnim.wingB = faceAnim.wingB + (int)((WING_B_NEUTRAL - faceAnim.wingB) * t);
        
        // ★ 嘴部复位
        faceAnim.mouthR = faceAnim.mouthR + (int)((MOUTH_R_NEUTRAL - faceAnim.mouthR) * t);
        faceAnim.mouthL = faceAnim.mouthL + (int)((MOUTH_L_NEUTRAL - faceAnim.mouthL) * t);
        faceAnim.mouthU = faceAnim.mouthU + (int)((MOUTH_U_NEUTRAL - faceAnim.mouthU) * t);
        faceAnim.mouthLower = faceAnim.mouthLower + (int)((MOUTH_LOWER_CLOSED - faceAnim.mouthLower) * t);
      } else {
        faceAnim.currentEmotion = EMO_IDLE;
        faceAnim.eyeState = EYE_IDLE;
        faceAnim.wingA = WING_A_NEUTRAL;
        faceAnim.wingB = WING_B_NEUTRAL;
        faceAnim.butt = BUTT_NEUTRAL;
        // ★ 重置嘴巴到闭合状态
        faceAnim.mouthR = MOUTH_R_NEUTRAL;
        faceAnim.mouthL = MOUTH_L_NEUTRAL;
        faceAnim.mouthU = MOUTH_U_NEUTRAL;
        faceAnim.mouthLower = MOUTH_LOWER_CLOSED;
        faceAnim.exprMouthActive = false;  // 关闭表情嘴部控制
        initBodyBreathing(now);
        eyeMicroNextMs = now + 500; eyeBigNextMs = now + 2000;
      }
      break;
    }
  }
}

// ==================== 情绪: 测试表情 ====================
// 用于测试所有舵机的动作范围
// 步骤：
// 0: 眼珠左右转10下
// 1: 眼珠上下转10下  
// 2: 眼皮眨眼和旋转3次
// 3: 嘴巴左歪右歪
// 4: 嘴巴上下开合假装说话
// 5: 恢复
void updateEmotionTest(uint32_t now) {
  uint32_t elapsed = now - faceAnim.emotionStepMs;
  
  switch (faceAnim.emotionStep) {
    case 0: {
      // 眼珠左右转10下（每次 500ms）
      int cycle = elapsed / 500;
      float phase = (float)(elapsed % 500) / 500.0f;
      
      if (cycle < 10) {
        // 左右摆动
        float swing = sinf(phase * 3.14159f * 2.0f);
        faceAnim.eyeLR = 90 + (int)(swing * (EYE_LR_MAX - 90));  // 最大范围
        faceAnim.eyeUD = 90;
      } else {
        faceAnim.eyeLR = 90;
        faceAnim.emotionStep = 1;
        faceAnim.emotionStepMs = now;
      }
      break;
    }
    case 1: {
      // 眼珠上下转10下（每次 500ms）
      int cycle = elapsed / 500;
      float phase = (float)(elapsed % 500) / 500.0f;
      
      if (cycle < 10) {
        // 上下摆动
        float swing = sinf(phase * 3.14159f * 2.0f);
        faceAnim.eyeUD = 90 + (int)(swing * (EYE_UD_MAX - 90));  // 最大范围
        faceAnim.eyeLR = 90;
      } else {
        faceAnim.eyeUD = 90;
        faceAnim.emotionStep = 2;
        faceAnim.emotionStepMs = now;
        faceAnim.emotionCount = 0;
      }
      break;
    }
    case 2: {
      // 眼皮眨眼和旋转3次（每次约 800ms）
      int cycle = elapsed / 800;
      float phase = (float)(elapsed % 800) / 800.0f;
      
      if (cycle < 3) {
        if (phase < 0.3f) {
          // 闭眼
          float t = phase / 0.3f;
          faceAnim.eyelidL = EYELID_L_NORMAL + (int)((EYELID_L_CLOSED - EYELID_L_NORMAL) * t);
          faceAnim.eyelidR = EYELID_R_NORMAL + (int)((EYELID_R_CLOSED - EYELID_R_NORMAL) * t);
        } else if (phase < 0.5f) {
          // 睁眼
          float t = (phase - 0.3f) / 0.2f;
          faceAnim.eyelidL = EYELID_L_CLOSED + (int)((EYELID_L_MAX_OPEN - EYELID_L_CLOSED) * t);
          faceAnim.eyelidR = EYELID_R_CLOSED + (int)((EYELID_R_MAX_OPEN - EYELID_R_CLOSED) * t);
        } else {
          // 眼皮旋转
          float rotPhase = (phase - 0.5f) / 0.5f;
          float rotSwing = sinf(rotPhase * 3.14159f * 2.0f);
          faceAnim.lidRotL = LID_ROT_L_NORMAL + (int)(rotSwing * 20);
          faceAnim.lidRotR = LID_ROT_R_NORMAL - (int)(rotSwing * 20);
          faceAnim.eyelidL = EYELID_L_NORMAL;
          faceAnim.eyelidR = EYELID_R_NORMAL;
        }
      } else {
        faceAnim.eyelidL = EYELID_L_NORMAL;
        faceAnim.eyelidR = EYELID_R_NORMAL;
        faceAnim.lidRotL = LID_ROT_L_NORMAL;
        faceAnim.lidRotR = LID_ROT_R_NORMAL;
        faceAnim.emotionStep = 3;
        faceAnim.emotionStepMs = now;
      }
      break;
    }
    case 3: {
      // 嘴巴左歪右歪（2000ms）
      float phase = (float)elapsed / 2000.0f;
      
      if (phase < 1.0f) {
        // 歪嘴效果：来回摆动
        float swing = sinf(phase * 3.14159f * 2.0f);
        if (swing > 0) {
          // 右边歪：右嘴角上扬，左嘴角下弯
          faceAnim.mouthR = MOUTH_R_NEUTRAL + (int)((MOUTH_R_UP - MOUTH_R_NEUTRAL) * swing);
          faceAnim.mouthL = MOUTH_L_NEUTRAL + (int)((MOUTH_L_DOWN - MOUTH_L_NEUTRAL) * swing);
        } else {
          // 左边歪：右嘴角下弯，左嘴角上扬
          faceAnim.mouthR = MOUTH_R_NEUTRAL + (int)((MOUTH_R_DOWN - MOUTH_R_NEUTRAL) * (-swing));
          faceAnim.mouthL = MOUTH_L_NEUTRAL + (int)((MOUTH_L_UP - MOUTH_L_NEUTRAL) * (-swing));
        }
        // 上嘴唇也跟着动
        faceAnim.mouthU = MOUTH_U_NEUTRAL + (int)(swing * 15);
      } else {
        faceAnim.mouthR = MOUTH_R_NEUTRAL;
        faceAnim.mouthL = MOUTH_L_NEUTRAL;
        faceAnim.mouthU = MOUTH_U_NEUTRAL;
        faceAnim.emotionStep = 4;
        faceAnim.emotionStepMs = now;
      }
      break;
    }
    case 4: {
      // 嘴巴开合假装说话（3000ms）
      float phase = (float)elapsed / 3000.0f;
      
      if (phase < 1.0f) {
        // 模拟说话：上下嘴唇开合 + 嘴角微动
        float talkPhase = sinf(elapsed * 0.02f);  // 快速开合
        float talkPhase2 = sinf(elapsed * 0.015f);
        
        // 下嘴唇开合（主要动作）
        faceAnim.mouthLower = MOUTH_LOWER_CLOSED + (int)((140 - MOUTH_LOWER_CLOSED) * (talkPhase * 0.5f + 0.5f));
        faceAnim.mouth = MOUTH_CLOSED + (int)((MOUTH_MAX_OPEN - MOUTH_CLOSED) * (talkPhase * 0.5f + 0.5f) * 0.6f);
        
        // 上嘴唇微动
        faceAnim.mouthU = MOUTH_U_NEUTRAL + (int)(talkPhase2 * 8);
        
        // 嘴角微动
        faceAnim.mouthR = MOUTH_R_NEUTRAL + (int)(talkPhase2 * 5);
        faceAnim.mouthL = MOUTH_L_NEUTRAL - (int)(talkPhase2 * 5);
      } else {
        faceAnim.emotionStep = 5;
        faceAnim.emotionStepMs = now;
      }
      break;
    }
    case 5: {
      // 恢复到中立
      if (elapsed < 500) {
        float t = (float)elapsed / 500.0f;
        faceAnim.mouthR = faceAnim.mouthR + (int)((MOUTH_R_NEUTRAL - faceAnim.mouthR) * t);
        faceAnim.mouthL = faceAnim.mouthL + (int)((MOUTH_L_NEUTRAL - faceAnim.mouthL) * t);
        faceAnim.mouthU = faceAnim.mouthU + (int)((MOUTH_U_NEUTRAL - faceAnim.mouthU) * t);
        faceAnim.mouthLower = faceAnim.mouthLower + (int)((MOUTH_LOWER_CLOSED - faceAnim.mouthLower) * t);
        faceAnim.mouth = faceAnim.mouth + (int)((MOUTH_CLOSED - faceAnim.mouth) * t);
      } else {
        // 完成测试，回到 idle
        faceAnim.currentEmotion = EMO_IDLE;
        faceAnim.eyeState = EYE_IDLE;
        faceAnim.mouthR = MOUTH_R_NEUTRAL;
        faceAnim.mouthL = MOUTH_L_NEUTRAL;
        faceAnim.mouthU = MOUTH_U_NEUTRAL;
        faceAnim.mouthLower = MOUTH_LOWER_CLOSED;
        faceAnim.mouth = MOUTH_CLOSED;
        faceAnim.exprMouthActive = false;
        Serial.println("[TEST] 测试表情完成");
      }
      break;
    }
  }
}

// ==================== 归位到中立状态 ====================
void faceAnimResetToNeutral() {
  uint32_t now = millis();
  
  faceAnim.eyeUD = 90;
  faceAnim.eyeLR = 90;
  faceAnim.eyelidL = EYELID_L_NORMAL;
  faceAnim.eyelidR = EYELID_R_NORMAL;
  faceAnim.lidRotL = LID_ROT_L_NORMAL;
  
  // 翅膀和屁股归位到中立位
  faceAnim.wingA = WING_A_NEUTRAL;
  faceAnim.wingB = WING_B_NEUTRAL;
  faceAnim.butt = BUTT_NEUTRAL;
  initBodyBreathing(now);
  faceAnim.lidRotR = LID_ROT_R_NORMAL;
  faceAnim.mouth = MOUTH_CLOSED;
  
  // ★ 嘴部舵机复位
  faceAnim.mouthR = MOUTH_R_NEUTRAL;
  faceAnim.mouthL = MOUTH_L_NEUTRAL;
  faceAnim.mouthU = MOUTH_U_NEUTRAL;
  faceAnim.mouthLower = MOUTH_LOWER_CLOSED;
  faceAnim.exprMouthActive = false;
  
  // 重置 jitter
  faceAnim.eyelidJitterL = 0;
  faceAnim.eyelidJitterR = 0;
  
  faceAnim.isBlinking = false;
  faceAnim.isMouthCute = false;
  faceAnim.currentEmotion = EMO_IDLE;
  faceAnim.eyeState = EYE_IDLE;
  faceAnim.eyeBaseUD = 90;
  faceAnim.eyeBaseLR = 90;
  
  // 重置计时器
  faceAnim.blinkNextMs = now + randInt(BLINK_INTERVAL_MIN_MS, BLINK_INTERVAL_MAX_MS);
  faceAnim.mouthCuteNextMs = now + randInt(MOUTH_CUTE_INTERVAL_MIN, MOUTH_CUTE_INTERVAL_MAX);
  faceAnim.eyelidJitterNextMs = now + randInt(EYELID_JITTER_INTERVAL_MIN, EYELID_JITTER_INTERVAL_MAX);
  
  // 重置眼球移动计时器
  eyeMicroNextMs = now + randInt(EYE_MICRO_INTERVAL_MIN, EYE_MICRO_INTERVAL_MAX);
  eyeBigNextMs = now + randInt(EYE_BIG_MOVE_INTERVAL_MIN, EYE_BIG_MOVE_INTERVAL_MAX);
  
  applyServos();
  Serial.println("[FACE] Reset to neutral");
}

// ==================== 启用/禁用动画 ====================
void faceAnimEnable(bool enable) {
  if (enable && !faceAnimEnabled) {
    // 刚启用时先归位
    faceAnimResetToNeutral();
    lastResetCheckMs = millis();
    Serial.println("[FACE] Animation ENABLED");
  } else if (!enable && faceAnimEnabled) {
    // 禁用时也归位
    faceAnimResetToNeutral();
    Serial.println("[FACE] Animation DISABLED");
  }
  faceAnimEnabled = enable;
}

// ==================== 主更新函数 ====================
// 眼球移动更新间隔（基于速度倍数）
#define ANIM_UPDATE_INTERVAL_MS  (int)(100 * ANIM_SPEED_MULTIPLIER)
// 眨眼检查间隔（固定50ms，不受速度倍数影响，确保眨眼及时）
#define BLINK_CHECK_INTERVAL_MS  50

uint32_t lastBlinkCheckMs = 0;

void faceAnimUpdate() {
  uint32_t now = millis();
  
  // 检查并释放超时的外部控制
  checkExternalServoTimeout();
  
  // 未启用时不执行任何动画
  if (!faceAnimEnabled) {
    return;
  }
  
  // 眼皮遥控更新（手部遮挡动画，最高优先级）
  updateEyelidRemote(now);
  
  // 嘴型更新已移到 taskMouthDriver（本地音频驱动，零延迟）
  // updateMouthShape();  // 不再使用 Python 远程命令
  
  // 眨眼检查（高频率，独立于主更新）
  // 遥控模式时跳过正常眨眼
  if (!eyelidRemoteControl && now - lastBlinkCheckMs >= BLINK_CHECK_INTERVAL_MS) {
    lastBlinkCheckMs = now;
    if (faceAnim.currentEmotion == EMO_IDLE) {
      updateIdleBlink(now);
    }
  }
  
  // 主更新频率（眼球移动等，受速度倍数影响）
  if (now - faceAnim.lastUpdateMs < ANIM_UPDATE_INTERVAL_MS) return;
  faceAnim.lastUpdateMs = now;
  
  // 定期归位检查点（防止误差累积）
  if (now - lastResetCheckMs > RESET_CHECK_INTERVAL_MS) {
    lastResetCheckMs = now;
    // 如果当前是 idle 模式，执行快速归位校验
    if (faceAnim.currentEmotion == EMO_IDLE && 
        !faceAnim.isBlinking && !faceAnim.isMouthCute &&
        faceAnim.eyeState == EYE_IDLE) {
      Serial.println("[FACE] Periodic reset checkpoint");
      faceAnim.lidRotL = LID_ROT_L_NORMAL;
      faceAnim.lidRotR = LID_ROT_R_NORMAL;
    }
  }
  
  // ★ 脖子舵机随机微动（始终执行，增加生动感）
  updateNeckMove(now);
  
  switch (faceAnim.currentEmotion) {
    case EMO_IDLE:
      // 眨眼已在上面独立更新（高频率）
      updateIdleMouthCute(now);
      updateIdleEyeMove(now);
      updateIdleBodyAction(now);  // 身体动作（翅膀扑腾、屁股扭动）
      break;
    case EMO_ANGRY:
      updateEmotionAngry(now);
      break;
    case EMO_SAD:
      updateEmotionSad(now);
      break;
    case EMO_HAPPY:
      updateEmotionHappy(now);
      break;
    case EMO_SPEECHLESS:
      updateEmotionSpeechless(now);
      break;
    case EMO_WINK:
      updateEmotionWink(now);
      break;
    case EMO_TEST:
      updateEmotionTest(now);
      break;
    case EMO_NORMAL:
      faceAnim.eyeUD = 90;
      faceAnim.eyeLR = 90;
      faceAnim.eyelidL = EYELID_L_NORMAL;
      faceAnim.eyelidR = EYELID_R_NORMAL;
      faceAnim.lidRotL = LID_ROT_L_NORMAL;
      faceAnim.lidRotR = LID_ROT_R_NORMAL;
      faceAnim.mouth = MOUTH_CLOSED;
      faceAnim.currentEmotion = EMO_IDLE;
      faceAnim.eyeState = EYE_IDLE;
      eyeMicroNextMs = now + 500; eyeBigNextMs = now + 2000;
      break;
    default:
      faceAnim.currentEmotion = EMO_IDLE;
      break;
  }
  
  applyServos();
}

// ==================== 设置情绪 ====================
void faceAnimSetEmotion(EmotionType emo) {
  if (emo >= EMO_COUNT) emo = EMO_IDLE;
  
  Serial.printf("[FACE] Set emotion: %s\n", EMOTION_NAMES[emo]);
  
  uint32_t now = millis();
  
  faceAnim.isBlinking = false;
  faceAnim.isMouthCute = false;
  
  faceAnim.emotionStartRotL = faceAnim.lidRotL;
  faceAnim.emotionStartRotR = faceAnim.lidRotR;
  
  faceAnim.currentEmotion = emo;
  faceAnim.emotionStep = 0;
  faceAnim.emotionStepMs = now;
  
  switch (emo) {
    case EMO_ANGRY:
      faceAnim.emotionEndMs = now + randInt(ANGRY_DURATION_MIN, ANGRY_DURATION_MAX);
      break;
    case EMO_SAD:
      faceAnim.emotionEndMs = now + randInt(SAD_DURATION_MIN, SAD_DURATION_MAX);
      break;
    case EMO_HAPPY:
      faceAnim.emotionEndMs = now + randInt(HAPPY_DURATION_MIN, HAPPY_DURATION_MAX);
      break;
    case EMO_SPEECHLESS:
      faceAnim.emotionEndMs = now + randInt(SPEECHLESS_DURATION_MIN, SPEECHLESS_DURATION_MAX);
      break;
    case EMO_WINK:
      faceAnim.emotionEndMs = now + randInt(WINK_DURATION_MIN, WINK_DURATION_MAX);
      break;
    case EMO_TEST:
      // 测试表情总时长：5s眼珠左右 + 5s眼珠上下 + 2.4s眼皮 + 2s嘴歪 + 3s说话 + 0.5s恢复 ≈ 18s
      faceAnim.emotionEndMs = now + 20000;
      Serial.println("[TEST] 开始测试表情");
      break;
    default:
      faceAnim.emotionEndMs = now + 1000;
      break;
  }
}

void faceAnimSetEmotionByName(const char* name) {
  for (int i = 0; i < EMO_COUNT; i++) {
    if (strcasecmp(name, EMOTION_NAMES[i]) == 0) {
      faceAnimSetEmotion((EmotionType)i);
      return;
    }
  }
  if (strcasecmp(name, "neutral") == 0 || strcasecmp(name, "reset") == 0) {
    faceAnimSetEmotion(EMO_NORMAL);
    return;
  }
  Serial.printf("[FACE] Unknown: %s -> idle\n", name);
  faceAnimSetEmotion(EMO_IDLE);
}

void faceAnimSetAudioMouth(bool active, float level) {
  faceAnim.audioMouthActive = active;
  faceAnim.audioMouthLevel = level < 0 ? 0 : (level > 1 ? 1 : level);
}

const char* faceAnimGetEmotionName() {
  return faceAnim.currentEmotion < EMO_COUNT ? EMOTION_NAMES[faceAnim.currentEmotion] : "unknown";
}

// ==================== 人脸追踪控制 ====================
// 设置眼球追踪目标位置（由服务端人脸检测调用）
void faceAnimSetEyeTrack(int lr, int ud) {
  // 限制在安全范围内
  lr = clampInt(lr, EYE_LR_MIN, EYE_LR_MAX);
  ud = clampInt(ud, EYE_UD_MIN, EYE_UD_MAX);
  
  faceTrackTargetLR = lr;
  faceTrackTargetUD = ud;
  faceTrackLastUpdateMs = millis();
  
  if (!faceTrackingActive) {
    faceTrackingActive = true;
    // 初始化当前位置为眼球当前位置，避免跳跃
    faceTrackCurrentLR = faceAnim.eyeLR;
    faceTrackCurrentUD = faceAnim.eyeUD;
    Serial.println("[FACE] Face tracking activated");
  }
}

// 停止人脸追踪，恢复随机眼球运动
void faceAnimStopEyeTrack() {
  if (faceTrackingActive) {
    faceTrackingActive = false;
    // 重置眼球运动计时器，立即恢复随机运动
    uint32_t now = millis();
    eyeMicroNextMs = now + randInt(EYE_MICRO_INTERVAL_MIN, EYE_MICRO_INTERVAL_MAX);
    eyeBigNextMs = now + randInt(EYE_BIG_MOVE_INTERVAL_MIN, EYE_BIG_MOVE_INTERVAL_MAX);
    Serial.println("[FACE] Face tracking stopped, resume random eye");
  }
}

// 更新人脸追踪眼球位置（在 faceAnimUpdate 中调用）
void updateFaceTrackEye(uint32_t now) {
  if (!faceTrackingActive) return;
  
  // 检查超时
  if (now - faceTrackLastUpdateMs > FACE_TRACK_TIMEOUT_MS) {
    faceAnimStopEyeTrack();
    return;
  }
  
  // 平滑插值到目标位置
  faceTrackCurrentLR += (faceTrackTargetLR - faceTrackCurrentLR) * FACE_TRACK_SMOOTH;
  faceTrackCurrentUD += (faceTrackTargetUD - faceTrackCurrentUD) * FACE_TRACK_SMOOTH;
  
  // 应用到眼球
  faceAnim.eyeLR = clampInt((int)faceTrackCurrentLR, EYE_LR_MIN, EYE_LR_MAX);
  faceAnim.eyeUD = clampInt((int)faceTrackCurrentUD, EYE_UD_MIN, EYE_UD_MAX);
}

// ==================== 眼皮遥控控制（手部遮挡动画）====================
// 眼皮遥控状态
bool eyelidRemoteControl = false;     // 是否处于遥控模式
int eyelidRemoteL = EYELID_L_NORMAL;  // 遥控目标左眼皮
int eyelidRemoteR = EYELID_R_NORMAL;  // 遥控目标右眼皮
uint32_t eyelidRemoteEndMs = 0;       // 遥控结束时间
uint8_t blinkFastCount = 0;           // 快速眨眼计数
uint32_t blinkFastNextMs = 0;         // 下次眨眼时间

// 快速眨眼（模拟被吓到）
void faceAnimEyelidBlinkFast() {
  eyelidRemoteControl = true;
  blinkFastCount = 4;  // 眨4次
  blinkFastNextMs = millis();
  eyelidRemoteEndMs = millis() + 600;  // 600ms 内完成
  Serial.println("[EYELID] 开始快速眨眼");
}

// 双眼闭合
void faceAnimEyelidCloseBoth() {
  eyelidRemoteControl = true;
  eyelidRemoteL = EYELID_L_CLOSED;
  eyelidRemoteR = EYELID_R_CLOSED;
  eyelidRemoteEndMs = 0;  // 无限期闭眼，直到收到其他命令
  blinkFastCount = 0;
  Serial.println("[EYELID] 双眼闭合");
}

// 睁一只眼偷看
void faceAnimEyelidPeek(bool leftEye) {
  eyelidRemoteControl = true;
  blinkFastCount = 0;
  if (leftEye) {
    // 睁开左眼，右眼保持闭合
    eyelidRemoteL = EYELID_L_NORMAL + 5;  // 稍微眯一点
    eyelidRemoteR = EYELID_R_CLOSED;
  } else {
    // 睁开右眼，左眼保持闭合
    eyelidRemoteL = EYELID_L_CLOSED;
    eyelidRemoteR = EYELID_R_NORMAL + 5;  // 稍微眯一点
  }
  eyelidRemoteEndMs = 0;  // 无限期，直到收到其他命令
  Serial.printf("[EYELID] 偷看: %s眼睁开\n", leftEye ? "左" : "右");
}

// 恢复正常
void faceAnimEyelidNormal() {
  eyelidRemoteControl = false;
  blinkFastCount = 0;
  eyelidRemoteL = EYELID_L_NORMAL;
  eyelidRemoteR = EYELID_R_NORMAL;
  eyelidRemoteEndMs = 0;
  Serial.println("[EYELID] 恢复正常");
}

// 更新眼皮遥控状态（在 faceAnimUpdate 中调用）
void updateEyelidRemote(uint32_t now) {
  if (!eyelidRemoteControl) return;
  
  // 检查是否超时
  if (eyelidRemoteEndMs > 0 && now > eyelidRemoteEndMs) {
    if (blinkFastCount == 0) {
      // 超时且不在快速眨眼，恢复正常
      faceAnimEyelidNormal();
      return;
    }
  }
  
  // 快速眨眼模式
  if (blinkFastCount > 0 && now >= blinkFastNextMs) {
    static bool blinkPhase = false;
    if (blinkPhase) {
      // 闭眼
      faceAnim.eyelidL = EYELID_L_CLOSED;
      faceAnim.eyelidR = EYELID_R_CLOSED;
      Serial.printf("[EYELID] 快速眨眼-闭眼 L=%d R=%d\n", faceAnim.eyelidL, faceAnim.eyelidR);
      blinkPhase = false;
      blinkFastNextMs = now + 60;  // 60ms 后睁眼
    } else {
      // 睁眼
      faceAnim.eyelidL = EYELID_L_NORMAL;
      faceAnim.eyelidR = EYELID_R_NORMAL;
      Serial.printf("[EYELID] 快速眨眼-睁眼 L=%d R=%d\n", faceAnim.eyelidL, faceAnim.eyelidR);
      blinkPhase = true;
      blinkFastCount--;
      blinkFastNextMs = now + 80;  // 80ms 后闭眼
      if (blinkFastCount == 0) {
        // 眨完后闭眼
        faceAnimEyelidCloseBoth();
      }
    }
    return;
  }
  
  // 应用遥控眼皮位置（快速过渡）
  if (blinkFastCount == 0) {
    // 快速过渡到目标位置（0.6 = 每次移动 60%）
    int diffL = eyelidRemoteL - faceAnim.eyelidL;
    int diffR = eyelidRemoteR - faceAnim.eyelidR;
    
    if (abs(diffL) > 2) {
      faceAnim.eyelidL += (int)(diffL * 0.6f);
    } else {
      faceAnim.eyelidL = eyelidRemoteL;
    }
    
    if (abs(diffR) > 2) {
      faceAnim.eyelidR += (int)(diffR * 0.6f);
    } else {
      faceAnim.eyelidR = eyelidRemoteR;
    }
  }
}

// ==================== 嘴型控制（元音驱动）====================
// 嘴型状态
bool mouthVowelEnabled = true;         // 是否启用元音嘴型控制
float mouthCurrentR = MOUTH_R_NEUTRAL;  // 右嘴角当前位置
float mouthCurrentL = MOUTH_L_NEUTRAL;  // 左嘴角当前位置
float mouthCurrentU = MOUTH_U_NEUTRAL;  // 上嘴唇当前位置
float mouthCurrentLower = MOUTH_LOWER_CLOSED;  // 下嘴唇当前位置

// 目标嘴型
MouthShape mouthTarget = MOUTH_SHAPE_CLOSED;
float mouthTargetVolume = 0;

// 平滑系数 - 越大越快到位
#define MOUTH_SMOOTH_FAST 0.8f   // 快速响应（嘴唇开合）- 几乎直接到位
#define MOUTH_SMOOTH_SLOW 0.6f   // 嘴角和上嘴唇也要快一点

// 根据元音字符获取嘴型
MouthShape getMouthShapeForVowel(char vowel) {
  switch (vowel) {
    case 'A': case 'a': return MOUTH_SHAPE_A;
    case 'O': case 'o': return MOUTH_SHAPE_O;
    case 'E': case 'e': return MOUTH_SHAPE_E;
    case 'I': case 'i': return MOUTH_SHAPE_I;
    case 'U': case 'u': return MOUTH_SHAPE_U;
    default: return MOUTH_SHAPE_CLOSED;
  }
}

// 设置目标嘴型（由 Python 端调用）
void setMouthShape(char vowel, float volume) {
  mouthTarget = getMouthShapeForVowel(vowel);
  mouthTargetVolume = constrain(volume, 0.0f, 1.0f);
  
  // 音量影响下嘴唇开合（叠加到基础嘴型）
  int volumeBoost = (int)(mouthTargetVolume * 35);  // 最多增加 35 度
  mouthTarget.lowerLip = constrain(mouthTarget.lowerLip + volumeBoost, 
                                    MOUTH_LOWER_CLOSED, MOUTH_LOWER_OPEN);
  
  // 调试日志
  static uint32_t lastLogMs = 0;
  if (millis() - lastLogMs > 500) {
    Serial.printf("[MOUTH] 设置嘴型: %c vol=%.2f -> R=%d L=%d U=%d Lower=%d\n",
      vowel, volume, mouthTarget.rightCorner, mouthTarget.leftCorner, 
      mouthTarget.upperLip, mouthTarget.lowerLip);
    lastLogMs = millis();
  }
}

// 更新嘴型舵机（在主循环中调用）
// 静态变量防止频繁更新
static uint32_t lastMouthUpdateMs = 0;
static int lastMouthR = -1, lastMouthL = -1, lastMouthU = -1, lastMouthLower = -1;

void updateMouthShape() {
  if (!mouthVowelEnabled) return;
  
  uint32_t now = millis();
  // 限制更新频率：每 20ms 更新一次（50Hz）
  if (now - lastMouthUpdateMs < 20) return;
  lastMouthUpdateMs = now;
  
  // 平滑插值
  mouthCurrentR += (mouthTarget.rightCorner - mouthCurrentR) * MOUTH_SMOOTH_FAST;
  mouthCurrentL += (mouthTarget.leftCorner - mouthCurrentL) * MOUTH_SMOOTH_FAST;
  mouthCurrentU += (mouthTarget.upperLip - mouthCurrentU) * MOUTH_SMOOTH_FAST;
  mouthCurrentLower += (mouthTarget.lowerLip - mouthCurrentLower) * MOUTH_SMOOTH_FAST;
  
  // 只有角度变化超过 1 度时才更新舵机
  int newR = (int)mouthCurrentR;
  int newL = (int)mouthCurrentL;
  int newU = (int)mouthCurrentU;
  int newLower = (int)mouthCurrentLower;
  
  if (abs(newR - lastMouthR) >= 1) {
    setServoAngle(CH_MOUTH_R, newR);
    lastMouthR = newR;
  }
  if (abs(newL - lastMouthL) >= 1) {
    setServoAngle(CH_MOUTH_L, newL);
    lastMouthL = newL;
  }
  if (abs(newU - lastMouthU) >= 1) {
    setServoAngle(CH_MOUTH_U, newU);
    lastMouthU = newU;
  }
  if (abs(newLower - lastMouthLower) >= 1) {
    setServoAngle(CH_MOUTH_LOWER, newLower);
    setServoAngle(CH_MOUTH, newLower);  // 兼容旧通道
    lastMouthLower = newLower;
  }
}

// 重置嘴型到闭合状态
void resetMouthShape() {
  mouthTarget = MOUTH_SHAPE_CLOSED;
  mouthTargetVolume = 0;
}

#endif

