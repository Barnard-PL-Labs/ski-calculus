/* Difficulty explorer: candidates-to-solution vs (target, cand_size).
 * FPGA-faithful: same generator/reducer as cpu_baseline.c / the engine.
 * work cap = 256 (FPGA work_depth), MAX_STEPS = 2000. cand_size up to ~43
 * fits the current template_depth=48; beyond that needs more BRAM/core. */
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

enum { APP=0, S=1, K=2, I=3, T=4, F=5 };
#define PREAMBLE 5
#define MAXN 256
#define MAX_STEPS 2000

typedef struct { int tag, left, right; } Node;
static uint32_t lfsr;
static inline uint32_t rnd(void){
    lfsr = (lfsr >> 1) ^ (-(int32_t)(lfsr & 1u) & 0x80200003u);
    return lfsr;
}
static int gen(Node *tmpl, int *count, int cand_size){
    tmpl[0]=(Node){I,0,0}; tmpl[1]=(Node){K,0,0};
    tmpl[2]=(Node){APP,1,0}; tmpl[3]=(Node){T,0,0}; tmpl[4]=(Node){F,0,0};
    for(int i=PREAMBLE;i<PREAMBLE+cand_size;i++){
        uint32_t r=rnd();
        if(i==PREAMBLE || ((r>>5)&7)<3){
            int sel=(r>>8)&3; int tag = sel==0?S : sel==1?K : I;
            tmpl[i]=(Node){tag,0,0};
        } else {
            int span=i-PREAMBLE;
            int l=PREAMBLE + (int)((((r>>10)&0xFF)*(uint32_t)span)>>8);
            int rr=PREAMBLE + (int)((((r>>18)&0xFF)*(uint32_t)span)>>8);
            tmpl[i]=(Node){APP,l,rr};
        }
    }
    *count=PREAMBLE+cand_size;
    return PREAMBLE+cand_size-1;
}
static int reduce(Node *h, int root, int count){
    int alloc=count, steps=0;
    for(;;){
        int cur=root, depth=0, a1=0,a2=0,a3=0, g1=0,g2=0,g3=0;
        while(h[cur].tag==APP){
            a3=a2; a2=a1; a1=cur; g3=g2; g2=g1; g1=h[cur].right;
            if(depth<3) depth++; cur=h[cur].left;
        }
        int ht=h[cur].tag;
        if(steps>=MAX_STEPS) return ht;
        if(ht==I && depth>=1){ h[a1]=h[g1]; steps++; continue; }
        if(ht==K && depth>=2){ h[a2]=h[g1]; steps++; continue; }
        if(ht==S && depth>=3){
            if(alloc+2>MAXN) return ht;
            h[alloc]=(Node){APP,g1,g3}; h[alloc+1]=(Node){APP,g2,g3};
            h[a3]=(Node){APP,alloc,alloc+1}; alloc+=2; steps++; continue;
        }
        return ht;
    }
}
static int fitness(Node *tmpl,int count,int root,const int *target,int n_inputs){
    Node work[MAXN]; int matched=0;
    for(int row=0; row<(1<<n_inputs); row++){
        memcpy(work, tmpl, sizeof(Node)*count);
        int acc=root, wp=count;
        for(int k=0;k<n_inputs+2;k++){
            int arg;
            if(k<n_inputs){ int bit=(row>>(n_inputs-1-k))&1; arg=bit?1:2; }
            else if(k==n_inputs) arg=3; else arg=4;
            work[wp]=(Node){APP,acc,arg}; acc=wp; wp++;
        }
        int ht=reduce(work, acc, wp);
        int got = ht==T?1 : ht==F?0 : -1;
        if(got==target[row]) matched++;
    }
    return matched;
}
/* search until solved (best==2^n) or cap candidates; return n-to-solution or -1 */
static long search(int cand_size,int n_inputs,const int*target,long cap,int*best_out){
    lfsr=0x12345678u; Node tmpl[MAXN]; int full=1<<n_inputs; int best=0;
    for(long n=1;n<=cap;n++){
        int count, root=gen(tmpl,&count,cand_size);
        int fit=fitness(tmpl,count,root,target,n_inputs);
        if(fit>best) best=fit;
        if(best==full){ *best_out=best; return n; }
    }
    *best_out=best; return -1;
}
int main(void){
    /* targets: MSB-first truth tables */
    int xor2[4]={0,1,1,0};
    int par3[8]={0,1,1,0,1,0,0,1};        /* 3-input parity (XOR3) */
    int maj3[8]={0,0,0,1,0,1,1,1};        /* 3-input majority */
    int mux3[8]={0,1,0,1,0,0,1,1};        /* 2:1 mux: s? b : a  (s=MSB) */
    int par4[16]; for(int r=0;r<16;r++){int p=0,x=r;while(x){p^=x&1;x>>=1;}par4[r]=p;}
    struct {const char*name;int n;int*t;} tg[]={
        {"XOR2",2,xor2},{"MUX3",3,mux3},{"MAJ3",3,maj3},{"PAR3",3,par3},{"PAR4",4,par4}};
    int sizes[]={16,24,32,40};
    long cap=20000000L;  /* ~60s/run single core */
    printf("target  n  cand_size  cands_to_solution  best/full\n");
    for(int ti=0; ti<5; ti++){
        for(int si=0; si<4; si++){
            int best; struct timespec a,b; clock_gettime(CLOCK_MONOTONIC,&a);
            long sol=search(sizes[si],tg[ti].n,tg[ti].t,cap,&best);
            clock_gettime(CLOCK_MONOTONIC,&b);
            double el=(b.tv_sec-a.tv_sec)+(b.tv_nsec-a.tv_nsec)/1e9;
            int full=1<<tg[ti].n;
            if(sol>0) printf("%-6s  %d  %8d  %15ld  %d/%d   (%.1fs)\n",
                             tg[ti].name,tg[ti].n,sizes[si],sol,best,full,el);
            else printf("%-6s  %d  %8d  %15s  %d/%d   (%.1fs, capped)\n",
                        tg[ti].name,tg[ti].n,sizes[si],">20M",best,full,el);
            fflush(stdout);
        }
    }
    return 0;
}
