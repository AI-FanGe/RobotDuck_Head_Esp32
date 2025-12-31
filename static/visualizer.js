// static/visualizer.js
class TechVisualizer {
    constructor(canvasId) {
        this.canvas = document.getElementById(canvasId);
        this.ctx = this.canvas.getContext('2d');
        this.ws = null;
        this.data = {};
        
        // 科技感配色方案
        this.colors = {
            primary: '#00D9FF',      // 青蓝色
            secondary: '#FF00FF',    // 品红/紫色
            accent: '#00FF88',       // 青绿色
            warning: '#FFAA00',      // 橙色
            background: '#000000',   // 黑色
            surface: '#0A0A0A',      // 深灰
            text: '#FFFFFF',         // 白色
            textMuted: '#888888',    // 灰色
            grid: '#1A1A1A',         // 网格色
            glow: '#00D9FF55'        // 发光效果
        };
        
        // 字体设置
        this.fonts = {
            title: 'bold 24px "Orbitron", "Microsoft YaHei", sans-serif',
            subtitle: 'bold 18px "Rajdhani", "Microsoft YaHei", sans-serif',
            body: '16px "Roboto", "Microsoft YaHei", sans-serif',
            small: '12px "Roboto", "Microsoft YaHei", sans-serif',
            tiny: '10px "Roboto", sans-serif'
        };
        
        this.setupCanvas();
        this.connectWebSocket();
    }
    
    setupCanvas() {
        // 设置画布大小
        const resizeCanvas = () => {
            const rect = this.canvas.getBoundingClientRect();
            this.canvas.width = rect.width * window.devicePixelRatio;
            this.canvas.height = rect.height * window.devicePixelRatio;
            this.ctx.scale(window.devicePixelRatio, window.devicePixelRatio);
        };
        
        window.addEventListener('resize', resizeCanvas);
        resizeCanvas();
    }
    
    connectWebSocket() {
        const wsUrl = `ws://${window.location.host}/ws/visualizer`;
        this.ws = new WebSocket(wsUrl);
        
        this.ws.onmessage = (event) => {
            try {
                this.data = JSON.parse(event.data);
                this.render();
            } catch (e) {
                console.error('Failed to parse visualization data:', e);
            }
        };
        
        this.ws.onclose = () => {
            setTimeout(() => this.connectWebSocket(), 1000);
        };
    }
    
    render() {
        const ctx = this.ctx;
        const width = this.canvas.width / window.devicePixelRatio;
        const height = this.canvas.height / window.devicePixelRatio;
        
        // 清空画布
        ctx.fillStyle = this.colors.background;
        ctx.fillRect(0, 0, width, height);
        
        // 绘制网格背景
        this.drawGrid(width, height);
        
        // 绘制HUD边框
        this.drawHUD(width, height);
        
        // 根据模式绘制内容
        if (this.data.mode === 'SEGMENT') {
            this.drawSegmentMode(width, height);
        } else if (this.data.mode === 'FLASH') {
            this.drawFlashMode(width, height);
        } else if (this.data.mode === 'TRACK') {
            this.drawTrackMode(width, height);
        }
        
        // 绘制手部骨骼
        if (this.data.hand) {
            this.drawHand(this.data.hand, width, height);
        }
        
        // 绘制FPS和状态信息
        this.drawStats(width, height);
    }
    
    drawGrid(width, height) {
        const ctx = this.ctx;
        ctx.strokeStyle = this.colors.grid;
        ctx.lineWidth = 0.5;
        
        const gridSize = 50;
        for (let x = 0; x < width; x += gridSize) {
            ctx.beginPath();
            ctx.moveTo(x, 0);
            ctx.lineTo(x, height);
            ctx.stroke();
        }
        for (let y = 0; y < height; y += gridSize) {
            ctx.beginPath();
            ctx.moveTo(0, y);
            ctx.lineTo(width, y);
            ctx.stroke();
        }
    }
    
    drawHUD(width, height) {
        const ctx = this.ctx;
        const margin = 20;
        
        // 四角装饰
        ctx.strokeStyle = this.colors.primary;
        ctx.lineWidth = 2;
        
        const cornerSize = 40;
        // 左上角
        ctx.beginPath();
        ctx.moveTo(margin, margin + cornerSize);
        ctx.lineTo(margin, margin);
        ctx.lineTo(margin + cornerSize, margin);
        ctx.stroke();
        
        // 右上角
        ctx.beginPath();
        ctx.moveTo(width - margin - cornerSize, margin);
        ctx.lineTo(width - margin, margin);
        ctx.lineTo(width - margin, margin + cornerSize);
        ctx.stroke();
        
        // 左下角
        ctx.beginPath();
        ctx.moveTo(margin, height - margin - cornerSize);
        ctx.lineTo(margin, height - margin);
        ctx.lineTo(margin + cornerSize, height - margin);
        ctx.stroke();
        
        // 右下角
        ctx.beginPath();
        ctx.moveTo(width - margin - cornerSize, height - margin);
        ctx.lineTo(width - margin, height - margin);
        ctx.lineTo(width - margin, height - margin - cornerSize);
        ctx.stroke();
    }
    
    drawSegmentMode(width, height) {
        const ctx = this.ctx;
        
        // 绘制检测到的物体
        if (this.data.segments) {
            this.data.segments.forEach((seg, index) => {
                if (seg.contour && seg.contour.length > 0) {
                    // 绘制轮廓
                    ctx.beginPath();
                    ctx.strokeStyle = seg.is_target ? this.colors.primary : this.colors.secondary;
                    ctx.lineWidth = seg.is_target ? 3 : 2;
                    
                    // 添加发光效果
                    if (seg.is_target) {
                        ctx.shadowColor = this.colors.primary;
                        ctx.shadowBlur = 10;
                    }
                    
                    const points = this.scalePoints(seg.contour, width, height);
                    ctx.moveTo(points[0][0], points[0][1]);
                    points.forEach(p => ctx.lineTo(p[0], p[1]));
                    ctx.closePath();
                    ctx.stroke();
                    
                    ctx.shadowBlur = 0;
                    
                    // 如果是目标，绘制中心标记
                    if (seg.is_target) {
                        const center = this.getContourCenter(points);
                        this.drawTargetMarker(center[0], center[1]);
                        
                        // 绘制面积信息
                        ctx.font = this.fonts.small;
                        ctx.fillStyle = this.colors.primary;
                        ctx.fillText(`Area: ${seg.area}`, center[0] + 20, center[1] - 20);
                    }
                }
            });
        }
        
        // 绘制状态文字
        if (this.data.auto_lock && this.data.auto_lock.active) {
            this.drawStatusText(
                `目标锁定中 Locking Target`,
                `${this.data.auto_lock.remaining.toFixed(1)}s`,
                width / 2,
                100,
                this.colors.warning
            );
        } else {
            this.drawStatusText(
                '扫描中 Scanning',
                '等待检测目标 Waiting for target',
                width / 2,
                100,
                this.colors.primary
            );
        }
    }
    
    drawFlashMode(width, height) {
        const ctx = this.ctx;
        
        if (this.data.flash && this.data.flash.mask_contour) {
            const progress = this.data.flash.progress || 0;
            const alpha = 0.3 + 0.4 * (0.5 * (1 + Math.sin(progress * 2 * Math.PI - Math.PI/2)));
            
            // 绘制闪烁轮廓
            ctx.beginPath();
            ctx.strokeStyle = this.colors.accent;
            ctx.lineWidth = 4;
            ctx.globalAlpha = alpha;
            
            const points = this.scalePoints(this.data.flash.mask_contour, width, height);
            ctx.moveTo(points[0][0], points[0][1]);
            points.forEach(p => ctx.lineTo(p[0], p[1]));
            ctx.closePath();
            
            // 填充
            ctx.fillStyle = this.colors.accent + '33';
            ctx.fill();
            ctx.stroke();
            
            ctx.globalAlpha = 1;
            
            // 绘制锁定动画
            const center = this.getContourCenter(points);
            this.drawLockAnimation(center[0], center[1], progress);
        }
        
        this.drawStatusText(
            '正在锁定目标 Locking Target',
            '准备追踪 Preparing to track',
            width / 2,
            100,
            this.colors.accent
        );
    }
    
    drawTrackMode(width, height) {
        const ctx = this.ctx;
        const tracking = this.data.tracking;
        
        if (!tracking) return;
        
        // 绘制追踪多边形
        if (tracking.polygon && tracking.polygon.length > 0) {
            ctx.beginPath();
            ctx.strokeStyle = this.colors.accent;
            ctx.lineWidth = 3;
            ctx.shadowColor = this.colors.accent;
            ctx.shadowBlur = 15;
            
            const points = this.scalePoints(tracking.polygon, width, height);
            ctx.moveTo(points[0][0], points[0][1]);
            points.forEach(p => ctx.lineTo(p[0], p[1]));
            ctx.closePath();
            ctx.stroke();
            
            ctx.shadowBlur = 0;
            
            // 绘制中心点
            if (tracking.center) {
                const center = this.scalePoint(tracking.center, width, height);
                ctx.fillStyle = this.colors.accent;
                ctx.beginPath();
                ctx.arc(center[0], center[1], 6, 0, Math.PI * 2);
                ctx.fill();
            }
        }
        
        // 绘制进度条
        this.drawProgressBars(tracking, width, height);
        
        // 绘制引导文字
        if (tracking.guidance) {
            const guidanceText = {
                '向前靠近': 'Move Closer',
                '后退': 'Move Back',
                '保持': 'Hold Position'
            };
            
            this.drawStatusText(
                tracking.guidance,
                guidanceText[tracking.guidance] || '',
                width / 2,
                height - 100,
                this.colors.warning
            );
        }
        
        // 如果触发了重新锁定
        if (tracking.relock_triggered) {
            this.drawStatusText(
                '已根据周边检测刷新追踪',
                'Tracking refreshed by peripheral detection',
                width / 2,
                170,
                this.colors.accent
            );
        }
    }
    
    drawHand(handData, width, height) {
        const ctx = this.ctx;
        
        if (!handData.landmarks) return;
        
        // 缩放坐标
        const landmarks = handData.landmarks.map(p => 
            this.scalePoint([p[0], p[1]], width, height)
        );
        
        // 绘制手部连接线
        ctx.strokeStyle = this.colors.secondary;
        ctx.lineWidth = 2;
        ctx.globalAlpha = 0.8;
        
        // MediaPipe手部连接定义
        const connections = [
            [0, 1], [1, 2], [2, 3], [3, 4],  // 拇指
            [0, 5], [5, 6], [6, 7], [7, 8],  // 食指
            [5, 9], [9, 10], [10, 11], [11, 12], // 中指
            [9, 13], [13, 14], [14, 15], [15, 16], // 无名指
            [13, 17], [17, 18], [18, 19], [19, 20], // 小指
            [0, 17] // 手腕连接
        ];
        
        connections.forEach(([start, end]) => {
            ctx.beginPath();
            ctx.moveTo(landmarks[start][0], landmarks[start][1]);
            ctx.lineTo(landmarks[end][0], landmarks[end][1]);
            ctx.stroke();
        });
        
        // 绘制关键点
        landmarks.forEach((point, i) => {
            ctx.fillStyle = this.colors.secondary;
            ctx.beginPath();
            ctx.arc(point[0], point[1], 3, 0, Math.PI * 2);
            ctx.fill();
        });
        
        ctx.globalAlpha = 1;
        
        // 绘制握持评分
        if (handData.grasp_score !== undefined) {
            ctx.font = this.fonts.body;
            ctx.fillStyle = this.colors.text;
            ctx.fillText(
                `握持评分 Grasp Score: ${handData.grasp_score.toFixed(2)}`,
                20,
                80
            );
        }
    }
    
    drawProgressBars(tracking, width, height) {
        const ctx = this.ctx;
        const barWidth = width * 0.25;
        const barHeight = 12;
        const x = 20;
        const y = height - 80;
        
        // 对齐进度条
        this.drawProgressBar(
            x, y - 30,
            barWidth, barHeight,
            tracking.align_score || 0,
            '对齐 Alignment',
            this.colors.primary
        );
        
        // 距离进度条
        this.drawProgressBar(
            x, y,
            barWidth, barHeight,
            tracking.range_score || 0,
            `距离 Distance (≈1)`,
            this.colors.secondary
        );
        
        // 显示比率
        if (tracking.ratio !== null && tracking.ratio !== undefined) {
            ctx.font = this.fonts.small;
            ctx.fillStyle = this.colors.text;
            ctx.fillText(
                `面积比 Ratio: ${tracking.ratio.toFixed(2)}`,
                x + barWidth + 20,
                y + 8
            );
        }
    }
    
    drawProgressBar(x, y, width, height, value, label, color) {
        const ctx = this.ctx;
        
        // 背景
        ctx.fillStyle = this.colors.surface;
        ctx.fillRect(x, y, width, height);
        
        // 边框
        ctx.strokeStyle = color + '44';
        ctx.lineWidth = 1;
        ctx.strokeRect(x, y, width, height);
        
        // 填充
        const fillWidth = width * Math.max(0, Math.min(1, value));
        const gradient = ctx.createLinearGradient(x, y, x + fillWidth, y);
        gradient.addColorStop(0, color + 'AA');
        gradient.addColorStop(1, color);
        ctx.fillStyle = gradient;
        ctx.fillRect(x, y, fillWidth, height);
        
        // 标签
        ctx.font = this.fonts.small;
        ctx.fillStyle = this.colors.textMuted;
        ctx.fillText(label, x, y - 5);
    }
    
    drawStats(width, height) {
        const ctx = this.ctx;
        
        // FPS显示
        ctx.font = this.fonts.body;
        ctx.fillStyle = this.colors.accent;
        ctx.fillText(`FPS: ${(this.data.fps || 0).toFixed(1)}`, 20, 40);
        
        // 模式显示
        const modeText = {
            'SEGMENT': '分割模式 Segmentation',
            'FLASH': '锁定模式 Locking',
            'TRACK': '追踪模式 Tracking'
        };
        
        ctx.fillStyle = this.colors.text;
        ctx.fillText(modeText[this.data.mode] || this.data.mode, width - 200, 40);
    }
    
    // 辅助函数
    scalePoint(point, width, height) {
        if (!this.data.frame_size) return [0, 0];
        return [
            point[0] * width / this.data.frame_size.width,
            point[1] * height / this.data.frame_size.height
        ];
    }
    
    scalePoints(points, width, height) {
        return points.map(p => this.scalePoint(p, width, height));
    }
    
    getContourCenter(points) {
        const sum = points.reduce((acc, p) => [acc[0] + p[0], acc[1] + p[1]], [0, 0]);
        return [sum[0] / points.length, sum[1] / points.length];
    }
    
    drawTargetMarker(x, y) {
        const ctx = this.ctx;
        ctx.strokeStyle = this.colors.primary;
        ctx.lineWidth = 2;
        
        // 十字准星
        const size = 20;
        ctx.beginPath();
        ctx.moveTo(x - size, y);
        ctx.lineTo(x - size/2, y);
        ctx.moveTo(x + size/2, y);
        ctx.lineTo(x + size, y);
        ctx.moveTo(x, y - size);
        ctx.lineTo(x, y - size/2);
        ctx.moveTo(x, y + size/2);
        ctx.lineTo(x, y + size);
        ctx.stroke();
        
        // 圆圈
        ctx.beginPath();
        ctx.arc(x, y, 10, 0, Math.PI * 2);
        ctx.stroke();
    }
    
    drawLockAnimation(x, y, progress) {
        const ctx = this.ctx;
        const radius = 30 + 10 * Math.sin(progress * Math.PI * 2);
        
        ctx.strokeStyle = this.colors.accent;
        ctx.lineWidth = 3;
        ctx.globalAlpha = 0.8;
        
        // 旋转的锁定环
        ctx.save();
        ctx.translate(x, y);
        ctx.rotate(progress * Math.PI * 2);
        
        // 绘制4个弧形
        for (let i = 0; i < 4; i++) {
            ctx.beginPath();
            ctx.arc(0, 0, radius, i * Math.PI/2 + 0.1, i * Math.PI/2 + Math.PI/2 - 0.1);
            ctx.stroke();
        }
        
        ctx.restore();
        ctx.globalAlpha = 1;
    }
    
    drawStatusText(mainText, subText, x, y, color) {
        const ctx = this.ctx;
        
        // 主文字（中文）
        ctx.font = this.fonts.subtitle;
        ctx.fillStyle = color;
        ctx.textAlign = 'center';
        ctx.fillText(mainText, x, y);
        
        // 副文字（英文）
        if (subText) {
            ctx.font = this.fonts.small;
            ctx.fillStyle = this.colors.textMuted;
            ctx.fillText(subText, x, y + 20);
        }
        
        ctx.textAlign = 'left';
    }
}

// 初始化
window.addEventListener('DOMContentLoaded', () => {
    window.visualizer = new TechVisualizer('tech-canvas');
}); 